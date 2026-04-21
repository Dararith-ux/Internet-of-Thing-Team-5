from machine import Pin, SPI
from mfrc522 import MFRC522
import sdcard
import os
import network
import urequests
import ntptime
import time
import gc

# ─────────────────────────────────────────
# WiFi credentials
# ─────────────────────────────────────────
SSID     = "ssid"
PASSWORD = "password"

# ─────────────────────────────────────────
# Firestore
# ─────────────────────────────────────────
PROJECT_ID   = "project-id"
FIRESTORE_URL = (
    "https://firestore.googleapis.com/v1/projects/"
    + PROJECT_ID
    + "/databases/(default)/documents/rfid_logs"
)

# ─────────────────────────────────────────
# Student database
# ─────────────────────────────────────────
STUDENTS = {
    "4119105685": {"name": "Messi",  "student_id": "STU001", "major": "Computer Engineering"},
    "2147337155": {"name": "Neymar", "student_id": "STU002", "major": "Computer Engineering"},
}

# ─────────────────────────────────────────
# Hardware setup
# ─────────────────────────────────────────
# Buzzer
buzzer = Pin(4, Pin.OUT)
buzzer.value(0)

# RFID – SPI1
spi_rfid = SPI(1, baudrate=1000000,
               sck=Pin(18), mosi=Pin(23), miso=Pin(19))
rdr = MFRC522(spi=spi_rfid, gpioRst=Pin(22), gpioCs=Pin(16))

# SD card – SPI2
spi_sd = SPI(2, baudrate=1000000,
             sck=Pin(14), mosi=Pin(15), miso=Pin(2))
sd_cs = Pin(13)

# ─────────────────────────────────────────
# WiFi connect
# ─────────────────────────────────────────
wifi = network.WLAN(network.STA_IF)
wifi.active(True)

def connect_wifi():
    if wifi.isconnected():
        return True

    print("Connecting to WiFi", end="")
    wifi.connect(SSID, PASSWORD)

    for _ in range(40):
        if wifi.isconnected():
            print("\nWiFi connected:", wifi.ifconfig())
            return True
        print(".", end="")
        time.sleep(0.5)

    print("\nWiFi connection failed")
    return False

def reconnect_wifi():
    if wifi.isconnected():
        return True
    print("WiFi dropped, reconnecting...")
    return connect_wifi()

# ─────────────────────────────────────────
# Helper: datetime string
# ─────────────────────────────────────────
def get_datetime():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        t[0], t[1], t[2], t[3], t[4], t[5]
    )

# ─────────────────────────────────────────
# Helper: buzzer
# ─────────────────────────────────────────
def beep(seconds):
    buzzer.value(1)
    time.sleep(seconds)
    buzzer.value(0)

# ─────────────────────────────────────────
# Helper: save to SD card (CSV)
# ─────────────────────────────────────────
def save_to_sd(uid, student, datetime_str):
    try:
        sd  = sdcard.SDCard(spi_sd, sd_cs)
        vfs = os.VfsFat(sd)
        os.mount(vfs, "/sd")

        write_header = "attendance.csv" not in os.listdir("/sd")

        with open("/sd/attendance.csv", "a") as f:
            if write_header:
                f.write("UID,Name,StudentID,Major,DateTime\n")
            line = "{},{},{},{},{}\n".format(
                uid,
                student["name"],
                student["student_id"],
                student["major"],
                datetime_str
            )
            f.write(line)

        os.umount("/sd")
        print("Saved to SD:", line.strip())

    except Exception as e:
        print("SD card error:", e)

# ─────────────────────────────────────────
# Helper: send to Firestore (with retry)
# ─────────────────────────────────────────
def send_to_firestore(uid, student, datetime_str):
    if not reconnect_wifi():
        print("Skipping Firestore – no WiFi")
        return

    gc.collect()  # free RAM before SSL handshake

    data = {
        "fields": {
            "uid":        {"stringValue": uid},
            "name":       {"stringValue": student["name"]},
            "student_id": {"stringValue": student["student_id"]},
            "major":      {"stringValue": student["major"]},
            "datetime":   {"stringValue": datetime_str}
        }
    }

    for attempt in range(1, 4):  # retry up to 3 times
        try:
            res = urequests.post(
                FIRESTORE_URL,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            print("Firestore OK (status {})".format(res.status_code))
            res.close()
            return  # success – stop retrying
        except Exception as e:
            print("Firestore attempt {}/3 failed: {}".format(attempt, e))
            time.sleep(2)

    print("Firestore: all retries failed – data is saved to SD only")

# ─────────────────────────────────────────
# Startup
# ─────────────────────────────────────────
connect_wifi()

try:
    ntptime.settime()
    print("Time synced via NTP")
except Exception as e:
    print("NTP sync failed (time may be wrong):", e)

print("\nReady – scan RFID card...\n")

# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────
while True:
    stat, tag_type = rdr.request(rdr.REQIDL)

    if stat == rdr.OK:
        stat, uid_bytes = rdr.anticoll()

        if stat == rdr.OK:
            uid_str = "".join([str(b) for b in uid_bytes])
            print("Card detected – UID:", uid_str)

            datetime_str = get_datetime()
            student = STUDENTS.get(uid_str)

            if student:
                # ── Valid student ──────────────────────────
                print("Valid student:", student["name"])
                beep(0.3)
                save_to_sd(uid_str, student, datetime_str)
                send_to_firestore(uid_str, student, datetime_str)
            else:
                # ── Unknown card ───────────────────────────
                print("Unknown Card")
                beep(3)

            print()       # blank line for readability
            time.sleep(2) # cooldown before next scan
