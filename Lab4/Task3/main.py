from machine import Pin, I2C
import time
import mlx90614
import network
from umqtt.simple import MQTTClient
import ujson

# WiFi credentials
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"
#MQTT settings
MQTT_BROKER = "test.mosquitto.org"
TOPIC = b"/aupp/zax/esp32_01/body_temp"

# 
#Connect WiFi
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)

while not wifi.isconnected():
    pass

print("WiFi Connected:", wifi.ifconfig())

# Connect MQTT
client = MQTTClient("ESP32_MLX90614", MQTT_BROKER)
client.connect()

# Setup I2C for MLX90614
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)

sensor = mlx90614.MLX90614(i2c)

while True:

    ambient_temp = sensor.read_ambient_temp()
    body_temp = sensor.read_object_temp()

    # Fever detection logic
    if body_temp >= 32.5:
        fever_flag = 1
    else:
        fever_flag = 0

    print("Ambient Temp:", ambient_temp)
    print("Body Temp:", body_temp)
    print("Fever Flag:", fever_flag)
    print("----------------------")

    # Send data to Node-RED
    data = {
        "ambient_temp": ambient_temp,
        "body_temp": body_temp,
        "fever_flag": fever_flag
    }

    client.publish(TOPIC, ujson.dumps(data))

    time.sleep(1)

