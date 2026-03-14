# main_blynk.py - ESP32 Smart Parking (Blynk Integration, no web server)

import network
import time
import machine
from machine import Pin, PWM, SoftI2C, time_pulse_us
import dht

try:
    import urequests
except Exception:
    urequests = None

# ====== CONFIG ======
WIFI_SSID = "water"
WIFI_PASS = "shibalshibal"

BLYNK_TOKEN = "rOjP_UvomsfQXDVRRomv7VjEPQhFg6uQ"
BLYNK_API   = "https://blynk.cloud/external/api"

# ====== BLYNK VIRTUAL PINS ======
# V0 - Servo control          (Slider: Integer 0-90) [only active in manual mode]
# V1 - IR Sensor Slot 1       (Label/Value display: "Available" or "Occupied")
# V2 - IR Sensor Slot 2       (Label/Value display: "Available" or "Occupied")
# V3 - IR Sensor Slot 3       (Label/Value display: "Available" or "Occupied")
# V4 - TM1637 / free count    (Value display: number of free slots)
# V5 - Manual mode toggle     (Switch widget: 0=auto, 1=manual)

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
BUTTON_DEBOUNCE_MS       = 250
FULL_NOTICE_COOLDOWN_MS  = 10000

TELEGRAM_BOT_TOKEN = "8606705484:AAHTau8hPwXBYDh9d4hov_A1AZCleUPquUI"
TELEGRAM_CHAT_ID   = "-5131364104"

LOOP_DELAY_MS      = 10
DISPLAY_UPDATE_MS  = 500
DHT_UPDATE_MS      = 2000
TM_UPDATE_MS       = 300
DISTANCE_SAMPLE_MS = 60

# Blynk update intervals (ms) - keep reasonable to avoid flooding
BLYNK_IR_UPDATE_MS    = 1000   # send IR slot status every 1s
BLYNK_POLL_V0_MS      = 500    # poll V0 (servo command) every 500ms
BLYNK_POLL_V5_MS      = 500    # poll V5 (manual mode) every 500ms
BLYNK_FREE_UPDATE_MS  = 1000   # send free count every 1s

GATE_OPEN_ANGLE   = 90
GATE_CLOSED_ANGLE = 0
GATE_HOLD_OPEN_MS = 2500

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

# Blynk state
AUTO_MODE              = True           # True = auto, False = manual
last_blynk_ir_ms       = 0
last_blynk_poll_v0_ms  = 0
last_blynk_poll_v5_ms  = 0
last_blynk_free_ms     = 0
last_ir_sent           = (None, None, None)   # track last sent values to avoid redundant sends
last_free_sent         = None

previous_slots_raw = None

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

# ====== BLYNK ======
def blynk_set(vpin, value):
    """Push a value to a Blynk virtual pin."""
    if urequests is None:
        return
    try:
        url = BLYNK_API + "/update?token=" + BLYNK_TOKEN + "&V" + str(vpin) + "=" + str(value)
        r = urequests.get(url)
        r.close()
    except Exception as e:
        print("Blynk set V" + str(vpin) + " error:", e)

def blynk_get(vpin):
    """Read a value from a Blynk virtual pin. Returns string or None on error."""
    if urequests is None:
        return None
    try:
        url = BLYNK_API + "/get?token=" + BLYNK_TOKEN + "&V" + str(vpin)
        r = urequests.get(url)
        raw = r.text
        r.close()
        # Blynk returns JSON array like ["1"] or ["0"]
        val = raw.strip().strip("[]\"' ")
        return val
    except Exception as e:
        print("Blynk get V" + str(vpin) + " error:", e)
        return None

def blynk_push_ir(slots_raw, free):
    """Send IR sensor states as 'Available' or 'Occupied' to V1, V2, V3."""
    global last_ir_sent
    labels = []
    for i in range(TOTAL_SLOTS):
        labels.append("Available" if slots_raw[i] == 1 else "Occupied")
    for i in range(TOTAL_SLOTS):
        if labels[i] != last_ir_sent[i]:
            blynk_set(i + 1, labels[i])   # V1, V2, V3
    last_ir_sent = tuple(labels)

def blynk_push_free(free):
    """Send free slot count to V4 (TM1637 counter)."""
    global last_free_sent
    if free != last_free_sent:
        blynk_set(4, free)
        last_free_sent = free

def blynk_poll_manual_mode():
    global AUTO_MODE
    val = blynk_get(5)
    if val is not None:
        new_manual = (val.strip() == "1")
        new_auto   = not new_manual
        if new_auto != AUTO_MODE:
            AUTO_MODE = new_auto
            print("Mode changed:", "AUTO" if AUTO_MODE else "MANUAL")
            # ── NEW: whenever mode switches, reset V0 slider to 0 ──
            blynk_set(0, 0)
            servo_write(GATE_CLOSED_ANGLE)
            print("V0 reset to 0, gate closed on mode switch")
    return AUTO_MODE

def blynk_poll_servo():
    """
    Read V0 (0-90) and move servo ONLY when in manual mode.
    V0 datastream: Integer, MIN=0, MAX=90, units=Degrees.
      V0 =  0  -> physical 0 deg   (fully closed)
      V0 =  0  -> physical 0 deg   (GATE_CLOSED_ANGLE - fully closed)
      V0 = 90  -> physical 90 deg  (GATE_OPEN_ANGLE - fully open)
    Raw 1:1 mapping - slider value = exact servo angle.
    In AUTO mode this is ignored - ultrasonic sensor controls the gate.
    """
    if AUTO_MODE:
        return
    val = blynk_get(0)
    if val is not None:
        try:
            v0_val   = int(float(val.strip()))
            physical = v0_to_physical_angle(v0_val)
            servo_write(physical)
            print("V0=" + str(v0_val) + " -> physical " + str(physical) + " deg (manual)")
        except Exception as e:
            print("V0 parse error:", e)
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
def check_slot_exits(now_ms, slots_raw, free):
    """Detect occupancy -> free transitions and bill accordingly."""
    global previous_slots_raw
    if previous_slots_raw is None:
        previous_slots_raw = slots_raw
        return
    for i in range(TOTAL_SLOTS):
        if previous_slots_raw[i] == 0 and slots_raw[i] == 1:
            bill_slot(i, now_ms, free)
    previous_slots_raw = slots_raw

def request_exit(now_ms, slots_raw, occ, source):
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
    # Exact same formula as original working code - no direction reversal
    duty = int((min(max(angle, 0), 180) / 180) * 75) + 40
    try:
        servo.duty(duty)
    except Exception:
        try:
            servo.duty_u16(int(duty * 65535 // 1023))
        except Exception as e:
            print("Servo error:", e)

def v0_to_physical_angle(v0_val):
    """
    Direct 1:1 raw angle mapping.
      V0 =  0  ->  0 deg   (GATE_CLOSED_ANGLE - fully closed)
      V0 = 90  ->  90 deg  (GATE_OPEN_ANGLE - fully open)
    What you set on the slider is exactly what the servo gets.
    """
    return min(max(int(v0_val), 0), 90)

def gate_open():
    global gate_state, gate_open_until
    servo_write(GATE_OPEN_ANGLE)
    gate_state = "open"
    gate_open_until = time.ticks_add(time.ticks_ms(), GATE_HOLD_OPEN_MS)

def gate_close():
    global gate_state
    servo_write(GATE_CLOSED_ANGLE)
    gate_state = "closed"
    # Sync Blynk V0 slider to 0 (= GATE_CLOSED_ANGLE) so slider matches real position
    blynk_set(0, GATE_CLOSED_ANGLE)
    print("Gate closed -> V0 reset to " + str(GATE_CLOSED_ANGLE))

def trigger_gate_open(ignore_cooldown=False):
    global last_open_ms
    now = time.ticks_ms()
    if ignore_cooldown or time.ticks_diff(now, last_open_ms) >= COOLDOWN_MS:
        gate_open()
        last_open_ms = now
        print("Gate opened")
        return True
    return False

last_open_ms = 0

def update_gate():
    """Auto-close gate after GATE_HOLD_OPEN_MS. Only applies in auto mode or after manual open."""
    if gate_state == "open" and time.ticks_diff(time.ticks_ms(), gate_open_until) >= 0:
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

# ====== STARTUP ======
print("=== STARTUP BEGIN ===")

print("[1] WiFi...")
ip = connect_wifi(WIFI_SSID, WIFI_PASS)
if not ip:
    print("[1] FAIL: no network")
else:
    print("[1] OK:", ip)

print("[2] Gate close...")
try:
    gate_close()
    print("[2] OK")
except Exception as e:
    print("[2] FAIL:", e)

print("[3] LCD clear...")
if lcd:
    try:
        lcd.clear()
        print("[3] OK")
    except Exception as e:
        print("[3] FAIL:", e)
else:
    print("[3] SKIP: no LCD")

print("[4] Boot slot states...")
try:
    _boot_raw = get_raw_slots()
    _boot_free, _boot_occ = count_from_raw(_boot_raw)
    _boot_ms = time.ticks_ms()
    print("[4] OK: raw=" + str(_boot_raw) + " occ=" + str(_boot_occ))
    for _i in range(TOTAL_SLOTS):
        if _boot_raw[_i] == 0:
            slot_tickets[_i] = {"id": next_ticket_id, "start_ms": _boot_ms}
            next_ticket_id += 1
except Exception as e:
    print("[4] FAIL:", e)
    _boot_occ = 0

print("[5] Initial Blynk push...")
try:
    _boot_raw = get_raw_slots()
    _boot_free, _boot_occ = count_from_raw(_boot_raw)
    blynk_push_ir(_boot_raw, _boot_free)
    blynk_push_free(_boot_free)
    blynk_set(5, 0)                    # V5: start in AUTO mode
    blynk_set(0, GATE_CLOSED_ANGLE)    # V0: set slider to 0 (closed position) on boot
    print("[5] OK")
except Exception as e:
    print("[5] FAIL:", e)

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

    # 1) Read IR sensors
    slots_raw = get_raw_slots()
    slots     = slots_from_raw(slots_raw)
    free, occ = count_from_raw(slots_raw)

    # 2) Exit button (physical)
    poll_exit_button(now, slots_raw, occ)

    # 3) Entry / exit detection
    process_pending_entry(now, slots_raw, free)
    check_slot_exits(now, slots_raw, free)

    # 4) Ultrasonic - only triggers auto gate in AUTO mode
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
                # Manual mode - notify only, gate not opened automatically
                send_telegram("[>] Car at entrance. Spots left: " + str(free) + " (manual)")
        entry_presence = near

    # 5) Gate auto-close timer
    update_gate()

    # 6) DHT sensor
    if time.ticks_diff(now, last_dht_ms) >= DHT_UPDATE_MS:
        update_dht()
        last_dht_ms = now

    # 7) TM1637 physical display
    if time.ticks_diff(now, last_tm_ms) >= TM_UPDATE_MS:
        update_tm(free)
        last_tm_ms = now

    # 8) LCD
    if time.ticks_diff(now, last_display_ms) >= DISPLAY_UPDATE_MS:
        update_display(free, occ, last_distance)
        last_display_ms = now

    # 9) Blynk: Poll V5 (manual mode toggle)
    #    Done before V0 so mode is current when we check servo command
    if time.ticks_diff(now, last_blynk_poll_v5_ms) >= BLYNK_POLL_V5_MS:
        blynk_poll_manual_mode()
        last_blynk_poll_v5_ms = now

    # 10) Blynk: Poll V0 (servo control) - only acts in MANUAL mode
    #     In AUTO mode this poll is skipped entirely to save bandwidth
    if not AUTO_MODE:
        if time.ticks_diff(now, last_blynk_poll_v0_ms) >= BLYNK_POLL_V0_MS:
            blynk_poll_servo()
            last_blynk_poll_v0_ms = now

    # 11) Blynk: Push IR slot states (V1, V2, V3) as "Available"/"Occupied"
    if time.ticks_diff(now, last_blynk_ir_ms) >= BLYNK_IR_UPDATE_MS:
        blynk_push_ir(slots_raw, free)
        last_blynk_ir_ms = now

    # 12) Blynk: Push free slot count (V4)
    if time.ticks_diff(now, last_blynk_free_ms) >= BLYNK_FREE_UPDATE_MS:
        blynk_push_free(free)
        last_blynk_free_ms = now

    time.sleep_ms(LOOP_DELAY_MS)

