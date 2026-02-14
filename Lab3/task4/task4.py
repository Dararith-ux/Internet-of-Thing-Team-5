import network
import time
import machine
import urequests as requests
from tm1637 import TM1637

# ---------- CONFIG ----------
WIFI_SSID = "Soth"
WIFI_PASS = "27082006"

BLYNK_TOKEN = "qabTiF0fzERmr9lomjmpLyxeGjAbN-EY"
BLYNK_API   = "https://blynk.cloud/external/api"

IR_PIN = 12
SERVO_PIN = 13
CLK_PIN = 17
DIO_PIN = 16

OPEN_ANGLE = 90
CLOSE_ANGLE = 0

# ---------- HARDWARE ----------
ir = machine.Pin(IR_PIN, machine.Pin.IN)
servo = machine.PWM(machine.Pin(SERVO_PIN), freq=50)
tm = TM1637(clk_pin=CLK_PIN, dio_pin=DIO_PIN, brightness=5)

# ---------- WIFI ----------
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(WIFI_SSID, WIFI_PASS)

print("Connecting to WiFi...")
while not wifi.isconnected():
    time.sleep(1)

print("WiFi connected!")

# ---------- FUNCTIONS ----------

def send_counter_to_blynk(value):
    try:
        url = f"{BLYNK_API}/update?token={BLYNK_TOKEN}&V4={value}"
        r = requests.get(url)
        r.close()
    except:
        print("Blynk counter send failed")


def move_servo(angle):
    original_angle = angle
    angle = 180 - angle  # keep reversed direction

    duty = int((angle / 180) * 102 + 26)
    servo.duty(duty)

    print("Servo moved to:", original_angle)


# ---------- MAIN ----------
print("Task 4 System Started...")

counter = 0
object_triggered = False

# Initial state
move_servo(CLOSE_ANGLE)
tm.show_digit(counter)
send_counter_to_blynk(counter)

while True:

    if ir.value() == 0:  # Object detected
        if not object_triggered:
            print("Object Detected!")

            # Increase counter
            counter += 1
            print("Counter:", counter)

            # Update TM1637
            tm.show_digit(counter)

            # Send to Blynk
            send_counter_to_blynk(counter)

            # Open servo
            move_servo(OPEN_ANGLE)
            time.sleep(3)

            # Close servo
            move_servo(CLOSE_ANGLE)

            object_triggered = True
    else:
        object_triggered = False

    time.sleep(0.2)

