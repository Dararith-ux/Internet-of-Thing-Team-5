from machine import Pin, ADC
import network
import time
from umqtt.simple import MQTTClient
import ujson

# WiFi credentials
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"

# MQTT broker (your computer IP running Node-RED)
MQTT_BROKER = "test.mosquitto.org"
TOPIC = b"/aupp/zax/esp32_01/gas"

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

# MQ-5 ADC setup
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

    # Gas Risk Classification
    if avg_value < 2100:
        risk_level = "SAFE"
    elif avg_value < 2600:
        risk_level = "WARNING"
    else:
        risk_level = "DANGER"

    print("Raw:", gas_value)
    print("Average:", avg_value)
    print("Risk:", risk_level)
    print("----------------")

    # Create JSON packet
    data = {
        "raw": gas_value,
        "average": avg_value,
        "risk_level": risk_level
    }

    client.publish(TOPIC, ujson.dumps(data))

    time.sleep(1)

