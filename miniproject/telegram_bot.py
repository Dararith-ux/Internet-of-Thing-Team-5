"""
bot.py — Telegram command bot for ESP32 Smart Parking
Run this on your laptop (same WiFi as the ESP32).

Requirements:
    pip3 install requests

Commands:
    /status     — full parking overview
    /slots      — per-slot detail with ticket & fee
    /temp       — temperature and humidity only
    /open       — open gate (MANUAL mode only)
    /close      — close gate (MANUAL mode only)
    /manual_on  — switch to manual mode
    /manual_off — switch back to auto mode
"""

import time
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN    = "8606705484:AAHTau8hPwXBYDh9d4hov_A1AZCleUPquUI"
CHAT_ID      = "-5131364104"          # only this chat can send commands

ESP32_IP     = "10.30.0.57:80"          # ← update if ESP32 IP changes
POLL_INTERVAL = 2                     # seconds between getUpdates calls
# ─────────────────────────────────────────────────────────────────────────────

API        = "https://api.telegram.org/bot{}".format(BOT_TOKEN)
ESP32_BASE = "http://{}".format(ESP32_IP)

offset = 0


# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg_send(chat_id, text):
    try:
        requests.post(
            API + "/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        print("tg_send error:", e)


def tg_get_updates():
    global offset
    try:
        r = requests.get(
            API + "/getUpdates",
            params={"timeout": 0, "offset": offset},
            timeout=10,
        )
        return r.json().get("result", [])
    except Exception as e:
        print("getUpdates error:", e)
        return []


# ── ESP32 helpers ─────────────────────────────────────────────────────────────

def esp32_get(path):
    try:
        r = requests.get(ESP32_BASE + path, timeout=5)
        return r
    except Exception as e:
        print("ESP32 request error:", e)
        return None


def esp32_status():
    r = esp32_get("/api/status")
    if r is None:
        return None
    try:
        return r.json()
    except Exception as e:
        print("JSON parse error:", e)
        return None


def esp32_unreachable(chat_id):
    tg_send(chat_id, "⚠️ Could not reach the ESP32.\nMake sure it is powered on and on the same WiFi.")


# ── Command handlers ──────────────────────────────────────────────────────────

def cmd_status(chat_id):
    data = esp32_status()
    if data is None:
        esp32_unreachable(chat_id)
        return

    slot_lines = []
    for s in data.get("slots", []):
        if s["state"] == "occupied":
            if s["ticket"]:
                slot_lines.append(
                    "  Slot {}: OCCUPIED — Ticket #{}, {}m, ${}".format(
                        s["slot"], s["ticket"], s["min"], s["fee"]
                    )
                )
            else:
                slot_lines.append("  Slot {}: OCCUPIED (no ticket)".format(s["slot"]))
        else:
            slot_lines.append("  Slot {}: FREE".format(s["slot"]))

    dist = data.get("dist")
    dist_str = "-- cm" if dist is None else "{} cm".format(dist)

    reply = (
        "🅿️ Smart Parking Status\n"
        "─────────────────────\n"
        "Free   : {}/{}\n"
        "Occ    : {}/{}\n"
        "Gate   : {}\n"
        "Mode   : {}\n"
        "Dist   : {}\n"
        "Temp   : {} °C\n"
        "Hum    : {} %\n"
        "─────────────────────\n"
        "{}"
    ).format(
        data["free"], data["total"],
        data["occupied"], data["total"],
        data["gate"].upper(),
        data["mode"].upper(),
        dist_str,
        data["temp"],
        data["hum"],
        "\n".join(slot_lines),
    )
    tg_send(chat_id, reply)


def cmd_slots(chat_id):
    data = esp32_status()
    if data is None:
        esp32_unreachable(chat_id)
        return

    lines = ["🅿️ Slot Details\n─────────────────────"]
    for s in data.get("slots", []):
        if s["state"] == "occupied":
            if s["ticket"]:
                lines.append(
                    "Slot {}: OCCUPIED\n  Ticket #{} | {}m elapsed | ${} due".format(
                        s["slot"], s["ticket"], s["min"], s["fee"]
                    )
                )
            else:
                lines.append("Slot {}: OCCUPIED (no ticket on record)".format(s["slot"]))
        else:
            lines.append("Slot {}: FREE".format(s["slot"]))

    tg_send(chat_id, "\n".join(lines))


def cmd_temp(chat_id):
    data = esp32_status()
    if data is None:
        esp32_unreachable(chat_id)
        return

    reply = (
        "🌡️ Temperature & Humidity\n"
        "─────────────────────\n"
        "Temp : {} °C\n"
        "Hum  : {} %"
    ).format(data["temp"], data["hum"])
    tg_send(chat_id, reply)


def cmd_open(chat_id):
    # Check mode first — only works in manual
    data = esp32_status()
    if data is None:
        esp32_unreachable(chat_id)
        return
    if data.get("mode") != "manual":
        tg_send(chat_id,
            "⛔ Gate control is only available in MANUAL mode.\n"
            "Send /manual_on first, then /open.")
        return
    r = esp32_get("/open")
    if r is None:
        esp32_unreachable(chat_id)
        return
    tg_send(chat_id, "✅ Gate opened.")


def cmd_close(chat_id):
    # Check mode first — only works in manual
    data = esp32_status()
    if data is None:
        esp32_unreachable(chat_id)
        return
    if data.get("mode") != "manual":
        tg_send(chat_id,
            "⛔ Gate control is only available in MANUAL mode.\n"
            "Send /manual_on first, then /close.")
        return
    r = esp32_get("/close")
    if r is None:
        esp32_unreachable(chat_id)
        return
    tg_send(chat_id, "🔒 Gate closed.")


def cmd_manual_on(chat_id):
    r = esp32_get("/manual")
    if r is None:
        esp32_unreachable(chat_id)
        return
    tg_send(chat_id,
        "🔧 Switched to MANUAL mode.\n"
        "Gate will NOT open automatically.\n"
        "Use /open and /close to control the gate.")


def cmd_manual_off(chat_id):
    r = esp32_get("/auto")
    if r is None:
        esp32_unreachable(chat_id)
        return
    tg_send(chat_id,
        "🤖 Switched to AUTO mode.\n"
        "Gate will open automatically when a car is detected.")


def cmd_unknown(chat_id, text):
    tg_send(
        chat_id,
        "❓ Unknown command: {}\n\n"
        "Available commands:\n"
        "/status     — parking overview\n"
        "/slots      — per-slot detail\n"
        "/temp       — temperature & humidity\n"
        "/manual_on  — switch to manual mode\n"
        "/manual_off — switch to auto mode\n"
        "/open       — open gate (manual only)\n"
        "/close      — close gate (manual only)".format(text),
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────

def dispatch(chat_id, text):
    cmd = text.strip().lower().split()[0].split("@")[0]
    print("Command from {}: {}".format(chat_id, cmd))

    if   cmd == "/status":     cmd_status(chat_id)
    elif cmd == "/slots":      cmd_slots(chat_id)
    elif cmd == "/temp":       cmd_temp(chat_id)
    elif cmd == "/open":       cmd_open(chat_id)
    elif cmd == "/close":      cmd_close(chat_id)
    elif cmd == "/manual_on":  cmd_manual_on(chat_id)
    elif cmd == "/manual_off": cmd_manual_off(chat_id)
    else:                      cmd_unknown(chat_id, text)


# ── Main loop ─────────────────────────────────────────────────────────────────

print("Bot started. Listening for commands in chat {}...".format(CHAT_ID))
print("ESP32 target: {}".format(ESP32_BASE))
print("Commands: /status  /slots  /temp  /manual_on  /manual_off  /open  /close")
print("Press Ctrl+C to stop.\n")

while True:
    updates = tg_get_updates()

    for update in updates:
        offset = update.get("update_id", 0) + 1

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue

        chat_id = str(msg.get("chat", {}).get("id", ""))

        if chat_id != str(CHAT_ID):
            print("Ignored message from unknown chat:", chat_id)
            continue

        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            continue

        dispatch(chat_id, text)

    time.sleep(POLL_INTERVAL)