from machine import Pin, I2C
import time
import tcs34725

# Initialize I2C and sensor
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
sensor = tcs34725.TCS34725(i2c)

print("Reading RGB values...")

while True:
    # Read raw RGB values
    r, g, b, c = sensor.read_raw()

    # Print to Serial Monitor
    print("R:", r, " G:", g, " B:", b)

    time.sleep(1)
