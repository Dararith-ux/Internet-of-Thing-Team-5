import network
import time
import machine
import urequests as requests

# ---------- CONFIG ----------
WIFI_SSID = "Soth"
WIFI_PASS = "27082006"

BLYNK_TOKEN = "qabTiF0fzERmr9lomjmpLyxeGjAbN-EY"
BLYNK_API   = "https://blynk.cloud/external/api"

IR_PIN = 12

# ---------- HARDWARE ----------
ir = machine.Pin(IR_PIN, machine.Pin.IN)

# ---------- WIFI ----------
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(WIFI_SSID, WIFI_PASS)

print("Connecting to WiFi...")
while not wifi.isconnected():
    time.sleep(1)

print("WiFi connected!")

# ---------- FUNCTION ----------
def send_ir_status(status):
    try:
        # Replace space with %20 for URL safety
        status = status.replace(" ", "%20")
        url = f"{BLYNK_API}/update?token={BLYNK_TOKEN}&V2={status}"
        r = requests.get(url)
        r.close()
    except:
        print("Blynk send failed")

# ---------- MAIN ----------
print("Reading IR Sensor...")

last_status = ""

while True:
    ir_value = ir.value()

    if ir_value == 0:
        status = "Detected"
    else:
        status = "Not Detected"

    # Send only if changed
    if status != last_status:
        send_ir_status(status)
        print("Sent to Blynk:", status)
        last_status = status

    time.sleep(2)

