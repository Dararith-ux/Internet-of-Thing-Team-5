from machine import Pin, I2C
import network
import time
import ujson
from umqtt.simple import MQTTClient
from bmp280 import BMP280

# WiFi credentials

SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"

# MQTT settings
MQTT_BROKER = "test.mosquitto.org"   # Node-RED computer IP
TOPIC = b"/aupp/zax/esp32_01/bmp280"

# Connect WiFi
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)

while not wifi.isconnected():
    pass

print("WiFi Connected:", wifi.ifconfig())

# MQTT connection
client = MQTTClient(b"/aupp/zax/esp32_01/bmp280", MQTT_BROKER)
client.connect()

# I2C setup
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)

# Initialize sensor
bmp = BMP280(i2c)

while True:

    temp = bmp.temperature
    pressure_pa = bmp.pressure
    pressure_hpa = pressure_pa / 100
    altitude = bmp.altitude

    timestamp = time.time()   # replace with DS3231 if used

    print("Temperature:", temp)
    print("Pressure:", pressure_hpa, "hPa")
    print("Altitude:", altitude, "m")
    print("Timestamp:", timestamp)
    print("----------------------")

    # Send JSON data
    data = {
        "temperature": temp,
        "pressure": pressure_hpa,
        "altitude": altitude,
        "timestamp": timestamp
    }

    client.publish(TOPIC, ujson.dumps(data))

    time.sleep(5)

