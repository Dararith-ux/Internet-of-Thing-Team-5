import network
import time
import machine
import urequests as requests

# ---------- CONFIG ----------
WIFI_SSID = "wifi"
WIFI_PASS = "password"

BLYNK_TOKEN = "qabTiF0fzERmr9lomjmpLyxeGjAbN-EY"
BLYNK_API   = "https://blynk.cloud/external/api"

IR_PIN = 12
SERVO_PIN = 13

OPEN_ANGLE = 90
CLOSE_ANGLE = 0

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
        status = status.replace(" ", "%20")
        url = f"{BLYNK_API}/update?token={BLYNK_TOKEN}&V2={status}"
        r = requests.get(url)
        r.close()
    except:
        print("IR send failed")


def move_servo(angle):
    original_angle = angle
    
    angle = 180 - angle

    duty = int((angle / 180) * 102 + 26)
    servo.duty(duty)

    print("Servo moved to:", original_angle)


# ---------- MAIN ----------
print("Automatic IR-Servo System Started...")

last_status = ""
object_triggered = False

# Start closed
move_servo(CLOSE_ANGLE)

while True:

    ir_value = ir.value()

    if ir_value == 0:
        status = "Detected"
    else:
        status = "Not Detected"

    # Send IR status to Blynk only when changed
    if status != last_status:
        send_ir_status(status)
        print("IR:", status)
        last_status = status

    # ---- AUTOMATIC SERVO ACTION ----
    if ir_value == 0 and not object_triggered:
        print("Opening Servo...")
        move_servo(OPEN_ANGLE)

        time.sleep(3)

        print("Closing Servo...")
        move_servo(CLOSE_ANGLE)

        object_triggered = True

    if ir_value == 1:
        object_triggered = False

    time.sleep(0.2)

