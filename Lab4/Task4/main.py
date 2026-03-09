from machine import Pin, ADC, I2C
import network
import time
import ujson
from umqtt.simple import MQTTClient
from bmp280 import BMP280

# =========================
# WiFi credentials
# =========================
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"

# =========================
# MQTT settings
# =========================
MQTT_BROKER = "test.mosquitto.org"
MQTT_CLIENT_ID = "ESP32_SENSOR_COMBINED"

TOPIC_GAS = b"/aupp/zax/esp32_01/gas"
TOPIC_BMP280 = b"/aupp/zax/esp32_01/bmp280"

# =========================
# Connect WiFi
# =========================
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)

print("Connecting to WiFi...", end="")
while not wifi.isconnected():
    print(".", end="")
    time.sleep(0.5)

print("\nWiFi Connected:", wifi.ifconfig())

# =========================
# Connect MQTT
# =========================
client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER)
client.connect()
print("Connected to MQTT broker:", MQTT_BROKER)

# =========================
# MQ-5 setup
# =========================
mq5 = ADC(Pin(33))
mq5.atten(ADC.ATTN_11DB)
mq5.width(ADC.WIDTH_12BIT)

readings = []
window_size = 5

# =========================
# BMP280 setup
# =========================
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
bmp = BMP280(i2c)

# =========================
# Timing control
# =========================
last_gas_time = time.ticks_ms()
last_bmp_time = time.ticks_ms()

GAS_INTERVAL = 1000      # 1 second
BMP_INTERVAL = 5000      # 5 seconds

# =========================
# Main loop
# =========================
while True:
    now = time.ticks_ms()

    # -------- MQ-5 every 1 second --------
    if time.ticks_diff(now, last_gas_time) >= GAS_INTERVAL:
        last_gas_time = now

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

        print("MQ-5 Raw:", gas_value)
        print("MQ-5 Average:", avg_value)
        print("MQ-5 Risk:", risk_level)
        print("----------------")

        gas_data = {
            "raw": gas_value,
            "average": avg_value,
            "risk_level": risk_level
        }

        client.publish(TOPIC_GAS, ujson.dumps(gas_data))

    # -------- BMP280 every 5 seconds --------
    if time.ticks_diff(now, last_bmp_time) >= BMP_INTERVAL:
        last_bmp_time = now

        temp = bmp.temperature
        pressure_pa = bmp.pressure
        pressure_hpa = pressure_pa / 100
        altitude = bmp.altitude
        timestamp = time.time()

        print("BMP280 Temperature:", temp)
        print("BMP280 Pressure:", pressure_hpa, "hPa")
        print("BMP280 Altitude:", altitude, "m")
        print("BMP280 Timestamp:", timestamp)
        print("----------------------")

        bmp_data = {
            "temperature": temp,
            "pressure": pressure_hpa,
            "altitude": altitude,
            "timestamp": timestamp
        }

        client.publish(TOPIC_BMP280, ujson.dumps(bmp_data))

    time.sleep_ms(100)
