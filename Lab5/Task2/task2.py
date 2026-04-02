from machine import Pin, I2C
import time
import tcs34725

# Initialize I2C and sensor
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
sensor = tcs34725.TCS34725(i2c)

print("Color Classification (RAW values)...")

def classify_color(r, g, b):
    if r > g and r > b:
        return "RED"
    elif g > r and g > b:
        return "GREEN"
    elif b > r and b > g:
        return "BLUE"
    else:
        return "UNKNOWN"

while True:
    # Read raw RGB values
    r, g, b, c = sensor.read_raw()

    # Classify using RAW values
    color = classify_color(r, g, b)

    # Print result
    print("RAW -> R:", r, " G:", g, " B:", b, " | Detected:", color)

    time.sleep(1)
