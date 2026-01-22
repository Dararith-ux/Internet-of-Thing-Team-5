import network
import urequests
import time
import ntptime

# =======================
# CONFIG
# =======================
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"

BOT_TOKEN = "8501835159:AAHJz2IJ6ZOZ3XOFRLz6VUHzNi4AZbX__wg"
GROUP_CHAT_ID = "-5140435435"   # your group id as string

POLL_INTERVAL_SEC = 2

API_BASE = "https://api.telegram.org/bot{}".format(BOT_TOKEN)
URL_UPDATES = API_BASE + "/getUpdates"

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

# =======================
# TIME SYNC (for HTTPS)
# =======================
try:
    ntptime.settime()
    print("Time synced (UTC)")
except Exception as e:
    print("NTP failed:", e)

# =======================
# HTTP GET JSON
# =======================
def http_get_json(url):
    r = None
    try:
        r = urequests.get(url)
        return r.json()
    finally:
        if r:
            r.close()

# =======================
# TELEGRAM MONITOR LOOP
# =======================
print("Listening... Type anything in the Telegram group and it will print here.")

offset = 0  # prevents reading the same message again

while True:
    try:
        updates_url = "{}?timeout=0&offset={}".format(URL_UPDATES, offset)
        data = http_get_json(updates_url)

        if data and data.get("ok") and data.get("result"):
            for update in data["result"]:
                update_id = update.get("update_id", 0)
                offset = update_id + 1

                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))

                # Only listen to your group
                if chat_id != str(GROUP_CHAT_ID):
                    continue

                sender = msg.get("from", {})
                name = sender.get("first_name", "")
                username = sender.get("username", "")
                text = msg.get("text", "")

                # Print any text message to terminal
                if text:
                    if username:
                        print("From: {} (@{})".format(name, username))
                    else:
                        print("From:", name)
                    print("Message:", text)
                    print("-" * 30)

        time.sleep(POLL_INTERVAL_SEC)

    except Exception as e:
        print("Loop error:", e)
        time.sleep(3)

