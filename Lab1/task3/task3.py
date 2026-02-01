import network
import urequests
import time
import ntptime
from machine import Pin
import dht

# =======================
# CONFIG
# =======================
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"

BOT_TOKEN = "8501835159:AAHJz2IJ6ZOZ3XOFRLz6VUHzNi4AZbX__wg"
GROUP_CHAT_ID = "-5140435435"   # Telegram group chat id

# Sensor & Relay Pins
DHT_PIN = 4
RELAY_PIN = 2
RELAY_ACTIVE_HIGH = True       # True if relay ON = pin HIGH, False if relay ON = pin LOW

POLL_INTERVAL_SEC = 2

API_BASE = "https://api.telegram.org/bot{}".format(BOT_TOKEN)
URL_SEND = API_BASE + "/sendMessage"
URL_UPDATES = API_BASE + "/getUpdates"

# =======================
# HARDWARE SETUP
# =======================
sensor = dht.DHT11(Pin(DHT_PIN))
relay = Pin(RELAY_PIN, Pin.OUT)

def relay_on():
    relay.value(1 if RELAY_ACTIVE_HIGH else 0)

def relay_off():
    relay.value(0 if RELAY_ACTIVE_HIGH else 1)

def relay_is_on():
    return relay.value() == (1 if RELAY_ACTIVE_HIGH else 0)

# Default relay OFF at start
relay_off()

# =======================
# HELPERS
# =======================
def url_encode(text: str) -> str:
    out = []
    for b in text.encode("utf-8"):
        if (48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122) or b in b"-_.~":
            out.append(chr(b))
        elif b == 32:
            out.append("+")
        else:
            out.append("%{:02X}".format(b))
    return "".join(out)

def http_get_json(url):
    r = None
    try:
        r = urequests.get(url)
        return r.json()
    finally:
        if r:
            r.close()

def http_post_form(url, form_str):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = None
    try:
        r = urequests.post(url, data=form_str, headers=headers)
        return r.status_code
    finally:
        if r:
            r.close()

def send_message(chat_id: str, text: str):
    payload = "chat_id={}&text={}".format(url_encode(chat_id), url_encode(text))
    status = http_post_form(URL_SEND, payload)
    print("Telegram send status:", status)

def read_temp_hum():
    sensor.measure()
    temp = sensor.temperature()
    hum = sensor.humidity()
    return temp, hum

def make_status_text():
    temp, hum = read_temp_hum()
    state = "ON ✅" if relay_is_on() else "OFF ❌"
    return (
        "📟 Status\n"
        "🌡️ Temperature: {:.2f} °C\n"
        "💧 Humidity: {:.2f} %\n"
        "🔌 Relay: {}"
    ).format(temp, hum, state)

# =======================
# WIFI CONNECT
# =======================
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)

print("Connecting to WiFi...")
while not wifi.isconnected():
    time.sleep(1)
print("WiFi connected:", wifi.ifconfig())

# Time sync (helps HTTPS cert validation on some boards)
try:
    ntptime.settime()
    print("Time synced (UTC)")
except Exception as e:
    print("NTP failed:", e)

print("Bot running in group:", GROUP_CHAT_ID)
print("Commands: /status, /on, /off")

# =======================
# MAIN LOOP
# =======================
offset = 0

while True:
    try:
        updates_url = "{}?timeout=0&offset={}".format(URL_UPDATES, offset)
        data = http_get_json(updates_url)

        if data and data.get("ok") and data.get("result"):
            for update in data["result"]:
                offset = update.get("update_id", 0) + 1

                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))

                # Only respond in your target group
                if chat_id != str(GROUP_CHAT_ID):
                    continue

                text = (msg.get("text") or "").strip()

                if text == "/status":
                    reply = make_status_text()
                    send_message(chat_id, reply)
                    print("Handled /status")

                elif text == "/on":
                    relay_on()
                    send_message(chat_id, "🔌 Relay turned ON ✅")
                    print("Handled /on (relay ON)")

                elif text == "/off":
                    relay_off()
                    send_message(chat_id, "🔌 Relay turned OFF ❌")
                    print("Handled /off (relay OFF)")

        time.sleep(POLL_INTERVAL_SEC)

    except Exception as e:
        print("Loop error:", e)
        time.sleep(3)

