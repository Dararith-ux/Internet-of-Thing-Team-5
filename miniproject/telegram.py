# main.py - ESP32 Smart Parking

import network
import socket
import select
import time
from machine import Pin, PWM, SoftI2C, time_pulse_us
import dht

try:
    import urequests
except Exception:
    urequests = None

# ====== CONFIG ======
WIFI_SSID = "Robotic WIFI"
WIFI_PASS = "rbtWIFI@2025"
WEB_PORT  = 80        # port 80 = no port number needed in browser URL

# ====== PINS ======
IR1 = Pin(32, Pin.IN)
IR2 = Pin(35, Pin.IN)
IR3 = Pin(34, Pin.IN)

TRIG = Pin(26, Pin.OUT)
ECHO = Pin(25, Pin.IN)

SERVO_PIN       = 13
EXIT_BUTTON_PIN = 27

TM_CLK  = 18
TM_DIO  = 19
LCD_SDA = 21
LCD_SCL = 22
DHT_PIN = 4

# ====== OPTIONAL HARDWARE ======
try:
    from tm1637 import TM1637
    tm = TM1637(TM_CLK, TM_DIO)
except Exception as e:
    print("TM1637 not available:", e)
    tm = None

try:
    from machine_i2c_lcd import I2cLcd
    i2c = SoftI2C(sda=Pin(LCD_SDA), scl=Pin(LCD_SCL), freq=400000)
    lcd = I2cLcd(i2c, 0x27, 2, 16)
except Exception as e:
    print("LCD not available:", e)
    lcd = None

try:
    dht_sensor = dht.DHT11(Pin(DHT_PIN))
except Exception as e:
    print("DHT11 not available:", e)
    dht_sensor = None

servo = PWM(Pin(SERVO_PIN), freq=50)

try:
    EXIT_BUTTON = Pin(EXIT_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
except Exception:
    EXIT_BUTTON = Pin(EXIT_BUTTON_PIN, Pin.IN)

# ====== PARAMETERS ======
TOTAL_SLOTS              = 3
DETECTION_DISTANCE_CM    = 10
COOLDOWN_MS              = 6000
PRICE_PER_MINUTE_USD     = 1
ENTRY_CONFIRM_TIMEOUT_MS = 12000
EXIT_CONFIRM_TIMEOUT_MS  = 18000
BUTTON_DEBOUNCE_MS       = 250
FULL_NOTICE_COOLDOWN_MS  = 10000

TELEGRAM_BOT_TOKEN = "8606705484:AAHTau8hPwXBYDh9d4hov_A1AZCleUPquUI"
TELEGRAM_CHAT_ID   = "-5131364104"

LOOP_DELAY_MS      = 10
DISPLAY_UPDATE_MS  = 500
DHT_UPDATE_MS      = 2000
TM_UPDATE_MS       = 300
DISTANCE_SAMPLE_MS = 60

GATE_OPEN_ANGLE   = 90
GATE_CLOSED_ANGLE = 0
GATE_HOLD_OPEN_MS = 2500

AUTO_MODE    = True
last_open_ms = 0

# ====== STATE ======
next_ticket_id = 1
slot_tickets   = [None, None, None]

last_display_ms          = 0
last_dht_ms              = 0
last_tm_ms               = 0
last_distance_ms         = 0
last_temp                = "--"
last_hum                 = "--"
last_distance            = None
last_lcd_line1           = ""
last_lcd_line2           = ""
last_tm_value            = None
gate_state               = "closed"
gate_open_until          = 0
entry_presence           = False
last_full_notice_ms      = 0
last_exit_button_state   = 1
last_exit_button_press_ms = 0
pending_entry            = None
telegram_warning_printed = False

# ====== WIFI ======
def connect_wifi(ssid, pwd):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(ssid, pwd)
        start = time.ticks_ms()
        while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), start) < 20000:
            time.sleep_ms(500)
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("WiFi connected:", ip)
        return ip
    print("WiFi failed")
    return None

# ====== TELEGRAM ======
_TG_URL_PREFIX = "https://api.telegram.org/bot{}/sendMessage?chat_id={}&text=".format(
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
)
_URL_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")

def _url_encode(text):
    out = []
    for ch in text:
        if ch in _URL_SAFE:
            out.append(ch)
        elif ch == " ":
            out.append("%20")
        elif ch == "\n":
            out.append("%0A")
        else:
            out.append("%{:02X}".format(ord(ch)))
    return "".join(out)

def send_telegram(message):
    global telegram_warning_printed
    if not TELEGRAM_BOT_TOKEN or urequests is None:
        if not telegram_warning_printed:
            print("Telegram disabled")
            telegram_warning_printed = True
        return
    try:
        resp = urequests.get(_TG_URL_PREFIX + _url_encode(message))
        resp.close()
    except Exception as e:
        print("Telegram error:", e)

# ====== BILLING ======
def calculate_fee(start_ms, end_ms):
    elapsed_sec = max(time.ticks_diff(end_ms, start_ms), 0) // 1000
    minutes = elapsed_sec // 60 + (1 if elapsed_sec % 60 else 0)
    minutes = max(minutes, 1)
    return minutes, minutes * PRICE_PER_MINUTE_USD

def fmt_duration(minutes):
    if minutes < 60:
        return str(minutes) + " min"
    return str(minutes // 60) + "h " + str(minutes % 60) + "min"

def assign_ticket(slot_idx, start_ms, free_after):
    global next_ticket_id
    t = {"id": next_ticket_id, "start_ms": start_ms}
    next_ticket_id += 1
    slot_tickets[slot_idx] = t
    msg = "[P] Ticket #" + str(t["id"]) + " issued\nSlot: " + str(slot_idx+1) + "\nSpots left: " + str(free_after)
    print(msg)
    send_telegram(msg)
    return t

def bill_slot(slot_idx, exit_ms, free_after):
    t = slot_tickets[slot_idx]
    slot_tickets[slot_idx] = None
    if t is None:
        msg = "Car left Slot " + str(slot_idx+1) + " (no ticket on record).\nSpots free: " + str(free_after)
        print(msg)
        send_telegram(msg)
        return
    minutes, fee = calculate_fee(t["start_ms"], exit_ms)
    msg = (
        "PARKING BILL\n"
        "Slot    : " + str(slot_idx+1) + "\n"
        "Ticket  : #" + str(t["id"]) + "\n"
        "Duration: " + fmt_duration(minutes) + "\n"
        "Amount  : $" + str(fee) + "\n"
        "Spots free: " + str(free_after) + "/" + str(TOTAL_SLOTS)
    )
    print(msg)
    send_telegram(msg)

# ====== ENTRY FLOW ======
def request_entry(now_ms, occ, free, dist_cm):
    global pending_entry
    if free <= 0:
        return False
    if trigger_gate_open():
        pending_entry = {"trigger_ms": now_ms, "slots_before": get_raw_slots()}
        send_telegram("[>] Car at entrance\nGate opened. Spots left: " + str(free))
        return True
    return False

def process_pending_entry(now_ms, slots_raw, free):
    global pending_entry
    if pending_entry is None:
        return
    before = pending_entry["slots_before"]
    for i in range(TOTAL_SLOTS):
        if before[i] == 1 and slots_raw[i] == 0:
            assign_ticket(i, pending_entry["trigger_ms"], free)
            pending_entry = None
            return
    if time.ticks_diff(now_ms, pending_entry["trigger_ms"]) > ENTRY_CONFIRM_TIMEOUT_MS:
        pending_entry = None
        print("Entry timeout")

# ====== EXIT FLOW ======
# previous_slots tracks the last known IR state so we can detect occupancy -> free transitions
previous_slots_raw = None

def check_slot_exits(now_ms, slots_raw, free):
    """Called every loop. If any slot changed from occupied(0) to free(1), bill it immediately."""
    global previous_slots_raw
    if previous_slots_raw is None:
        previous_slots_raw = slots_raw
        return
    for i in range(TOTAL_SLOTS):
        if previous_slots_raw[i] == 0 and slots_raw[i] == 1:
            # Slot i just became free - car left
            bill_slot(i, now_ms, free)
    previous_slots_raw = slots_raw

def request_exit(now_ms, slots_raw, occ, source):
    """Gate open request from button or web - just opens the gate."""
    if not trigger_gate_open(ignore_cooldown=True):
        return False
    print("Exit gate opened by " + source)
    if occ <= 0:
        send_telegram("Gate opened (" + source + ") but parking is empty.")
    return True

# ====== BUTTON ======
def poll_exit_button(now_ms, slots_raw, occ):
    global last_exit_button_state, last_exit_button_press_ms
    state = EXIT_BUTTON.value()
    if state == 0 and last_exit_button_state == 1:
        if time.ticks_diff(now_ms, last_exit_button_press_ms) >= BUTTON_DEBOUNCE_MS:
            last_exit_button_press_ms = now_ms
            request_exit(now_ms, slots_raw, occ, "button")
    last_exit_button_state = state

# ====== SERVO / GATE ======
def servo_write(angle):
    duty = int((min(max(angle, 0), 180) / 180) * 75) + 40
    try:
        servo.duty(duty)
    except Exception:
        try:
            servo.duty_u16(int(duty * 65535 // 1023))
        except Exception as e:
            print("Servo error:", e)

def gate_open():
    global gate_state, gate_open_until
    servo_write(GATE_OPEN_ANGLE)
    gate_state = "open"
    gate_open_until = time.ticks_add(time.ticks_ms(), GATE_HOLD_OPEN_MS)

def gate_close():
    global gate_state
    servo_write(GATE_CLOSED_ANGLE)
    gate_state = "closed"

def trigger_gate_open(ignore_cooldown=False):
    global last_open_ms
    now = time.ticks_ms()
    if ignore_cooldown or time.ticks_diff(now, last_open_ms) >= COOLDOWN_MS:
        gate_open()
        last_open_ms = now
        print("Gate opened")
        return True
    return False

def update_gate():
    # In manual mode the gate stays open until /close is sent explicitly.
    # The auto-close timer only applies in AUTO mode.
    if AUTO_MODE and gate_state == "open" and time.ticks_diff(time.ticks_ms(), gate_open_until) >= 0:
        gate_close()
        print("Gate closed")

# ====== ULTRASONIC ======
TRIG.value(0)

def get_distance_cm():
    TRIG.value(1)
    time.sleep_us(10)
    TRIG.value(0)
    duration = time_pulse_us(ECHO, 1, 25000)
    if duration <= 0:
        return None
    dist = duration * 0.01715
    return round(dist, 2) if 0 < dist <= 400 else None

def get_stable_distance():
    d1 = get_distance_cm()
    time.sleep_ms(5)
    d2 = get_distance_cm()
    if d1 is None and d2 is None: return None
    if d1 is None: return d2
    if d2 is None: return d1
    return d1 if d1 <= d2 else d2

# ====== SLOTS ======
def get_raw_slots():
    return (IR1.value(), IR2.value(), IR3.value())

def slots_from_raw(raw):
    return ("occupied" if raw[0] == 0 else "free",
            "occupied" if raw[1] == 0 else "free",
            "occupied" if raw[2] == 0 else "free")

def count_from_raw(raw):
    occ = (raw[0] == 0) + (raw[1] == 0) + (raw[2] == 0)
    return max(TOTAL_SLOTS - occ, 0), occ

# ====== DISPLAY ======
def safe_lcd_write(line1, line2):
    global last_lcd_line1, last_lcd_line2
    if not lcd:
        return
    line1 = (line1 + "                ")[:16]
    line2 = (line2 + "                ")[:16]
    try:
        if line1 != last_lcd_line1:
            lcd.move_to(0, 0)
            lcd.putstr(line1)
            last_lcd_line1 = line1
        if line2 != last_lcd_line2:
            lcd.move_to(0, 1)
            lcd.putstr(line2)
            last_lcd_line2 = line2
    except Exception as e:
        print("LCD error:", e)

def update_dht():
    global last_temp, last_hum
    if not dht_sensor:
        return
    try:
        dht_sensor.measure()
        last_temp = str(dht_sensor.temperature())
        last_hum  = str(dht_sensor.humidity())
    except Exception:
        last_temp = "--"
        last_hum  = "--"

def update_tm(free):
    global last_tm_value
    if tm and free != last_tm_value:
        try:
            tm.show_digit(free)
            last_tm_value = free
        except Exception as e:
            print("TM error:", e)

def update_display(free, occ, dist):
    dist_text = "--" if dist is None else str(int(dist))
    safe_lcd_write(
        "Free:" + str(free) + " Occ:" + str(occ),
        "T:" + last_temp + " H:" + last_hum + " D:" + dist_text
    )

# ====== WEB PAGE ======
# CSS kept as bytes - never goes through .format() so curly braces are safe
_CSS = b"""<style>
body{background:#222;color:#fff;font-family:sans-serif;text-align:center;margin:0}
.w{background:#333;padding:14px;max-width:360px;margin:16px auto;border-radius:8px}
h2{margin:6px 0}
.r{display:flex;gap:6px;margin:10px 0}
.s{flex:1;padding:10px 4px;border-radius:6px;font-weight:bold;font-size:13px}
.f{background:#2e7d32;color:#fff}
.o{background:#c62828;color:#fff}
p{font-size:13px;margin:3px 0}
.ga{color:#69f0ae}.gm{color:#ff5252}
button{width:120px;height:36px;font-size:12px;margin:3px;border:none;border-radius:5px;background:#1565c0;color:#fff;cursor:pointer}
</style>"""

def handle_client(client, free, occ, dist, slots, slots_raw):
    global AUTO_MODE
    try:
        client.settimeout(5.0)

        req = b""
        try:
            req = client.recv(512)
        except Exception:
            pass

        if not req:
            return

        # Parse path
        path = "/"
        try:
            first_line = req.split(b"\r\n")[0]
            parts = first_line.split(b" ")
            if len(parts) >= 2:
                path = parts[1].decode("utf-8")
        except Exception:
            pass

        print("Request:", path)

        # Actions
        now = time.ticks_ms()
        if   "/open"   in path: request_exit(now, slots_raw, occ, "web")
        elif "/close"  in path: gate_close()
        elif "/auto"   in path: AUTO_MODE = True
        elif "/manual" in path: AUTO_MODE = False

        # [NEW] /api/status — tiny JSON blob for bot.py (no TLS, plain HTTP only)
        if "/api/status" in path:
            slot_parts = []
            for i in range(3):
                tk = slot_tickets[i]
                occupied = (slots_raw[i] == 0)
                if occupied and tk is not None:
                    esec = max(time.ticks_diff(time.ticks_ms(), tk["start_ms"]), 0) // 1000
                    emin = max(esec // 60, 0)
                    efee = max(emin, 1) * PRICE_PER_MINUTE_USD
                    slot_parts.append(
                        '{"slot":' + str(i+1) +
                        ',"state":"occupied"' +
                        ',"ticket":' + str(tk["id"]) +
                        ',"min":' + str(emin) +
                        ',"fee":' + str(efee) + '}'
                    )
                elif occupied:
                    slot_parts.append(
                        '{"slot":' + str(i+1) + ',"state":"occupied","ticket":null,"min":0,"fee":0}'
                    )
                else:
                    slot_parts.append(
                        '{"slot":' + str(i+1) + ',"state":"free","ticket":null,"min":0,"fee":0}'
                    )
            dist_val = "null" if last_distance is None else str(last_distance)
            json_body = (
                '{"free":' + str(free) +
                ',"occupied":' + str(occ) +
                ',"total":' + str(TOTAL_SLOTS) +
                ',"gate":"' + gate_state + '"' +
                ',"mode":"' + ("auto" if AUTO_MODE else "manual") + '"' +
                ',"temp":"' + last_temp + '"' +
                ',"hum":"' + last_hum + '"' +
                ',"dist":' + dist_val +
                ',"slots":[' + ",".join(slot_parts) + ']}'
            ).encode("utf-8")
            client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
            client.sendall(json_body)
            return   # skip HTML page

        # Build page
        mode_str = "AUTO" if AUTO_MODE else "MANUAL"
        dstr = "--" if dist is None else str(dist)
        mc   = "ga" if mode_str == "AUTO" else "gm"
        ref  = '<meta http-equiv="refresh" content="3">' if mode_str == "AUTO" else ""

        cards = ""
        for i in range(3):
            occ_slot = slots[i] == "occupied"
            cl  = "o" if occ_slot else "f"
            lbl = "Occupied" if occ_slot else "Free"
            tk  = slot_tickets[i]
            extra = ""
            if tk is not None:
                esec  = max(time.ticks_diff(time.ticks_ms(), tk["start_ms"]), 0) // 1000
                emin  = max(esec // 60, 0)
                efee  = max(emin, 1) * PRICE_PER_MINUTE_USD
                extra = "<br><small>#" + str(tk["id"]) + " " + str(emin) + "m $" + str(efee) + "</small>"
            cards += '<div class="s ' + cl + '">Slot ' + str(i+1) + '<br>' + lbl + extra + '</div>'

        html = (
            '<!DOCTYPE html><html><head>'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Parking</title>' + ref +
            '</head><body><div class="w">'
            '<h2>Smart Parking</h2>'
            '<div class="r">' + cards + '</div>'
            '<p>Free: <b>' + str(free) + '</b> | Occ: <b>' + str(occ) + '</b></p>'
            '<p>Dist: <b>' + dstr + '</b>cm | Gate: <b>' + gate_state.upper() + '</b></p>'
            '<p>Mode: <span class="' + mc + '">' + mode_str + '</span></p>'
            '<a href="/open"><button>Open Exit Gate</button></a>'
            '<a href="/close"><button>Close Gate</button></a><br>'
            '<a href="/auto"><button>Auto Mode</button></a>'
            '<a href="/manual"><button>Manual Mode</button></a>'
            '</div></body></html>'
        ).encode("utf-8")

        # Send response in chunks: header, CSS bytes, body
        client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
        client.sendall(_CSS)
        client.sendall(html)

    except Exception as e:
        print("Client error:", e)
    finally:
        try:
            client.close()
        except Exception:
            pass

# ====== START SERVER ======
def start_server(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    s.listen(3)
    s.setblocking(False)   # KEY FIX: non-blocking so main loop never stalls
    print("Server listening on port", port)
    return s

# ====== STARTUP ======
print("=== STARTUP BEGIN ===")

print("[1] WiFi...")
ip = connect_wifi(WIFI_SSID, WIFI_PASS)
if not ip:
    print("[1] FAIL: no network")
else:
    print("[1] OK:", ip)

print("[2] Web server...")
server = None
if ip:
    try:
        server = start_server(WEB_PORT)
        print("[2] OK: http://" + ip + ":" + str(WEB_PORT))
    except Exception as e:
        print("[2] FAIL:", e)
        server = None
else:
    print("[2] SKIP: no IP")

print("[3] Gate close...")
try:
    gate_close()
    print("[3] OK")
except Exception as e:
    print("[3] FAIL:", e)

print("[4] LCD clear...")
if lcd:
    try:
        lcd.clear()
        print("[4] OK")
    except Exception as e:
        print("[4] FAIL:", e)
else:
    print("[4] SKIP: no LCD")

print("[5] Boot slot states...")
try:
    _boot_raw = get_raw_slots()
    _boot_free, _boot_occ = count_from_raw(_boot_raw)
    _boot_ms = time.ticks_ms()
    print("[5] OK: raw=" + str(_boot_raw) + " occ=" + str(_boot_occ))
    for _i in range(TOTAL_SLOTS):
        if _boot_raw[_i] == 0:
            slot_tickets[_i] = {"id": next_ticket_id, "start_ms": _boot_ms}
            next_ticket_id += 1
except Exception as e:
    print("[5] FAIL:", e)
    _boot_occ = 0

print("[6] Telegram...")
try:
    if _boot_occ > 0:
        send_telegram("Rebooted. " + str(_boot_occ) + "/" + str(TOTAL_SLOTS) +
                      " slots occupied. Tickets from reboot time.")
    print("[6] OK")
except Exception as e:
    print("[6] FAIL:", e)

print("=== SYSTEM READY ===")

# ====== MAIN LOOP ======
while True:
    now = time.ticks_ms()

    # 1) Read IR
    slots_raw = get_raw_slots()
    slots     = slots_from_raw(slots_raw)
    free, occ = count_from_raw(slots_raw)

    # 2) Exit button
    poll_exit_button(now, slots_raw, occ)

    # 3) Pending entry / direct exit detection
    process_pending_entry(now, slots_raw, free)
    check_slot_exits(now, slots_raw, free)

    # 4) Ultrasonic
    if time.ticks_diff(now, last_distance_ms) >= DISTANCE_SAMPLE_MS:
        last_distance    = get_stable_distance()
        last_distance_ms = now
        near = last_distance is not None and last_distance <= DETECTION_DISTANCE_CM
        if near and not entry_presence:
            if free <= 0:
                if time.ticks_diff(now, last_full_notice_ms) >= FULL_NOTICE_COOLDOWN_MS:
                    send_telegram("[X] Car at entrance. Parking FULL.")
                    last_full_notice_ms = now
            elif AUTO_MODE and gate_state == "closed":
                request_entry(now, occ, free, last_distance)
            else:
                send_telegram("[>] Car at entrance. Spots left: " + str(free) + " (manual)")
        entry_presence = near

    # 5) Gate auto-close
    update_gate()

    # 6) DHT
    if time.ticks_diff(now, last_dht_ms) >= DHT_UPDATE_MS:
        update_dht()
        last_dht_ms = now

    # 7) TM1637
    if time.ticks_diff(now, last_tm_ms) >= TM_UPDATE_MS:
        update_tm(free)
        last_tm_ms = now

    # 8) LCD
    if time.ticks_diff(now, last_display_ms) >= DISPLAY_UPDATE_MS:
        update_display(free, occ, last_distance)
        last_display_ms = now

    # 9) Web
    if server:
        try:
            r, _, _ = select.select([server], [], [], 0)
            if r:
                client, caddr = server.accept()
                print("Web connection from", caddr)
                handle_client(client, free, occ, last_distance, slots, slots_raw)
        except Exception as e:
            print("Server loop error:", e)

    time.sleep_ms(LOOP_DELAY_MS)

