import network
import time
import machine
import urequests as requests

# ---------- CONFIG ----------
WIFI_SSID = "Soth"
WIFI_PASS = "27082006"

BLYNK_TOKEN = "qabTiF0fzERmr9lomjmpLyxeGjAbN-EY"
BLYNK_API   = "https://blynk.cloud/external/api"

IR_PIN = 12
SERVO_PIN = 13

# ---------- HARDWARE ----------
ir = machine.Pin(IR_PIN, machine.Pin.IN)
servo = machine.PWM(machine.Pin(SERVO_PIN), freq=50)

# ---------- WIFI ----------
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(WIFI_SSID, WIFI_PASS)

print("Connecting to WiFi...")
while not wifi.isconnected():
    time.sleep(1)

print("WiFi connected!")

# ---------- FUNCTIONS ----------

def send_ir_status(status):
    try:
        status = status.replace(" ", "%20")  # Fix space for URL
        url = f"{BLYNK_API}/update?token={BLYNK_TOKEN}&V2={status}"
        r = requests.get(url)
        r.close()
    except:
        print("IR send failed")


def read_slider_v3():
    try:
        url = f"{BLYNK_API}/get?token={BLYNK_TOKEN}&V3"
        r = requests.get(url)
        value = int(str(r.text).strip('[]"'))
        r.close()
        return value
    except:
        print("Slider read failed")
        return None


def move_servo(angle):
    # Reverse direction (swap 0 and 180)
    angle = 180 - angle

    # Convert angle (0–180) to PWM duty for ESP32
    duty = int((angle / 180) * 102 + 26)
    servo.duty(duty)

    print("Servo moved to:", angle)


# ---------- MAIN ----------
print("System Started...")

last_status = ""
last_angle = -1

while True:

    # ---- IR SENSOR ----
    ir_value = ir.value()

    if ir_value == 0:
        status = "Detected"
    else:
        status = "Not Detected"

    if status != last_status:
        send_ir_status(status)
        print("IR:", status)
        last_status = status

    # ---- SERVO CONTROL ----
    angle = read_slider_v3()

    if angle is not None and angle != last_angle:
        move_servo(angle)
        last_angle = angle

    time.sleep(1)

