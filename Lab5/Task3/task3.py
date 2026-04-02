from machine import Pin, I2C
import neopixel
import time
import tcs34725

# Sensor setup
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
sensor = tcs34725.TCS34725(i2c)

# NeoPixel setup (same as your code)
led = neopixel.NeoPixel(Pin(23), 24)

def classify_color(r, g, b):
    if r > g and r > b:
        return "RED"
    elif g > r and g > b:
        return "GREEN"
    elif b > r and b > g:
        return "BLUE"
    else:
        return "UNKNOWN"

def set_all(color):
    for i in range(24):
        led[i] = color
    led.write()

print("System Started...")

while True:
    r, g, b, c = sensor.read_raw()
    color = classify_color(r, g, b)

    # Control NeoPixel based on detected color
    if color == "RED":
        set_all((255, 0, 0))
    elif color == "GREEN":
        set_all((0, 255, 0))
    elif color == "BLUE":
        set_all((0, 0, 255))
    else:
        set_all((0, 0, 0))  # turn off if unknown

    print("RAW -> R:", r, " G:", g, " B:", b, "| Detected:", color)

    time.sleep(1)
