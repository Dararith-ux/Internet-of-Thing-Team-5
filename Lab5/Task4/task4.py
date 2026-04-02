from machine import Pin, PWM, I2C
import time
import tcs34725

# =========================
# TCS34725 Sensor Setup
# =========================
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
sensor = tcs34725.TCS34725(i2c)

# =========================
# Motor Setup
# =========================
IN1 = Pin(27, Pin.OUT)
IN2 = Pin(26, Pin.OUT)

ENA = PWM(Pin(14))
ENA.freq(1000)

# =========================
# Motor Functions
# =========================
def motor_forward(speed):
    IN1.value(1)
    IN2.value(0)
    ENA.duty(speed)

def motor_stop():
    IN1.value(0)
    IN2.value(0)
    ENA.duty(0)

# =========================
# Color Classification
# =========================
def classify_color(r, g, b):
    if r > g and r > b:
        return "RED"
    elif g > r and g > b:
        return "GREEN"
    elif b > r and b > g:
        return "BLUE"
    else:
        return "UNKNOWN"

print("Task 4: Motor Control with Color Sensor Started...")

while True:
    # Read raw RGB values from sensor
    r, g, b, c = sensor.read_raw()

    # Detect color
    color = classify_color(r, g, b)

    # Control motor speed based on detected color
    if color == "RED":
        pwm_value = 700
        motor_forward(pwm_value)

    elif color == "GREEN":
        pwm_value = 500
        motor_forward(pwm_value)

    elif color == "BLUE":
        pwm_value = 300
        motor_forward(pwm_value)

    else:
        pwm_value = 0
        motor_stop()

    # Print result
    print("R:", r, "G:", g, "B:", b, "| Detected:", color, "| PWM:", pwm_value)

    time.sleep(1)
