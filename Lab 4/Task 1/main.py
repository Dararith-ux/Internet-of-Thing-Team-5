from machine import Pin, ADC
import network
import time
from umqtt.simple import MQTTClient

# WiFi credentials
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"

# MQTT settings
MQTT_BROKER = "test.mosquitto.org"   # your computer IP
TOPIC = b"/aupp/zax/esp32_01/gas	"

# Connect WiFi
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)

while not wifi.isconnected():
    pass

print("WiFi Connected:", wifi.ifconfig())

# Connect MQTT
client = MQTTClient("ESP32_MQ5", MQTT_BROKER)
client.connect()

# Setup MQ5 sensor
mq5 = ADC(Pin(33))
mq5.atten(ADC.ATTN_11DB)
mq5.width(ADC.WIDTH_12BIT)

readings = []
window_size = 5

while True:

    gas_value = mq5.read()

    readings.append(gas_value)

    if len(readings) > window_size:
        readings.pop(0)

    avg_value = sum(readings) / len(readings)

    print("Raw:", gas_value)
    print("Average:", avg_value)

    # Send to Node-RED
    client.publish(TOPIC, str(avg_value))

    time.sleep(1)

