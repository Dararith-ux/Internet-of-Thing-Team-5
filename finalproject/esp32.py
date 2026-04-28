import network
import urequests
import time
from machine import Pin, SoftI2C
from machine_i2c_lcd import I2cLcd

# ── CONFIG ────────────────────────────────────────────────
WIFI_SSID  = "your_wifi_name"
WIFI_PASS  = "your_wifi_password"
SERVER_URL = "http://192.168.x.x:5000/capture_result"

BUZZER_PIN = 4
LCD_ADDR   = 0x27   # try 0x3F if LCD stays blank
LCD_ROWS   = 2
LCD_COLS   = 16
SDA_PIN    = 21
SCL_PIN    = 22

POLL_EVERY = 1      # seconds between polls
# ──────────────────────────────────────────────────────────

# ── HARDWARE SETUP ────────────────────────────────────────
buzzer = Pin(BUZZER_PIN, Pin.OUT)
buzzer.value(0)

i2c = SoftI2C(sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400000)
lcd = I2cLcd(i2c, LCD_ADDR, LCD_ROWS, LCD_COLS)


# ── WIFI ──────────────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return

    lcd.clear()
    lcd.putstr("Connecting WiFi.")
    print("Connecting to WiFi...")

    wlan.connect(WIFI_SSID, WIFI_PASS)
    attempts = 0
    while not wlan.isconnected():
        time.sleep(0.5)
        attempts += 1
        print(".")
        if attempts > 40:
            lcd.clear()
            lcd.putstr("WiFi Failed!")
            lcd.move_to(0, 1)
            lcd.putstr("Check settings")
            print("WiFi failed.")
            return

    ip = wlan.ifconfig()[0]
    print("WiFi connected:", ip)
    lcd.clear()
    lcd.putstr("WiFi Connected!")
    lcd.move_to(0, 1)
    # IP can exceed 16 chars on rare cases, slice to be safe
    lcd.putstr(ip[:LCD_COLS])
    time.sleep(2)


# ── BUZZER PATTERNS ───────────────────────────────────────
def buzz(duration_ms):
    buzzer.value(1)
    time.sleep_ms(duration_ms)
    buzzer.value(0)

def buzz_correct():
    # One clean long buzz — correct!
    buzz(300)

def buzz_add_more():
    # Two short pulses — not enough
    buzz(150)
    time.sleep_ms(100)
    buzz(150)

def buzz_excess():
    # Three rapid pulses — too many
    buzz(80)
    time.sleep_ms(60)
    buzz(80)
    time.sleep_ms(60)
    buzz(80)


# ── LCD DISPLAY ───────────────────────────────────────────
# All strings must be <= 16 chars for a 16x2 LCD
# Row 1: status
# Row 2: action / instruction

def update_lcd(capture_status):
    status  = capture_status.get("status", "no_target")
    diff    = capture_status.get("diff", 0)

    lcd.clear()

    if status == "no_target":
        lcd.putstr("No target set")   # 14 chars
        lcd.move_to(0, 1)
        lcd.putstr("Set target first") # 16 chars

    elif status == "correct":
        lcd.putstr("Correct!  :)")     # 12 chars
        lcd.move_to(0, 1)
        lcd.putstr("Count is perfect") # 16 chars

    elif status == "add_more":
        missing = abs(diff)
        lcd.putstr("Too few pills!")   # 14 chars
        lcd.move_to(0, 1)
        action = f"Add {missing} more"
        # e.g. "Add 3 more" = 10 chars, safe
        # cap at 16 just in case
        lcd.putstr(action[:LCD_COLS])

    elif status == "remove":
        lcd.putstr("Too many pills!")  # 15 chars
        lcd.move_to(0, 1)
        action = f"Remove {diff}"
        # e.g. "Remove 2" = 8 chars, safe
        lcd.putstr(action[:LCD_COLS])

    else:
        lcd.putstr("Waiting...")       # 10 chars
        lcd.move_to(0, 1)
        lcd.putstr("Press capture")    # 13 chars


# ── MAIN LOOP ─────────────────────────────────────────────
def main():
    connect_wifi()

    lcd.clear()
    lcd.putstr("PillCount AI")         # 12 chars
    lcd.move_to(0, 1)
    lcd.putstr("Ready!")               # 6 chars
    time.sleep(1)

    last_capture_id = -1

    while True:
        try:
            res  = urequests.get(SERVER_URL, timeout=5)
            data = res.json()
            res.close()

            capture_id     = data.get("capture_id", 0)
            capture_status = data.get("capture_status", {})
            status         = capture_status.get("status", "no_target")

            # Only react when a NEW capture has happened
            if capture_id != last_capture_id and capture_id > 0:
                print(f"Capture #{capture_id} — status: {status}")

                update_lcd(capture_status)

                if status == "correct":
                    buzz_correct()
                elif status == "add_more":
                    buzz_add_more()
                elif status == "remove":
                    buzz_excess()

                last_capture_id = capture_id

        except Exception as e:
            print("Error:", e)
            lcd.clear()
            lcd.putstr("Server error!")    # 13 chars
            lcd.move_to(0, 1)
            err = str(e)[:LCD_COLS]
            lcd.putstr(err)
            last_capture_id = -1           # reset so it re-fires on reconnect

        time.sleep(POLL_EVERY)


main()