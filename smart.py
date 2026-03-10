import network
import socket
import time
import ntptime
import urequests
import dht
from machine import Pin, PWM, SoftI2C, time_pulse_us


# =========================
# CONFIGURATION
# =========================
WIFI_SSID = "Robotic WIFI"
WIFI_PASSWORD = "rbtWIFI@2025"

TELEGRAM_BOT_TOKEN = "8606705484:AAHTau8hPwXBYDh9d4hov_A1AZCleUPquUI"
TELEGRAM_CHAT_ID = "-1703677527"  # group or personal chat id as string

BLYNK_TOKEN = "zW9Srjr0OmqEh8hAEhNjj9B8zAGUTBTk"
BLYNK_API = "https://blynk.cloud/external/api"

# Pins (adjust to your exact wiring)
PIN_TRIG = 27
PIN_ECHO = 26

PIN_IR_SLOTS = [32, 33, 25]  # 3 parking slot sensors (active LOW)

PIN_SERVO = 13
PIN_DHT = 4
PIN_RELAY = 2
RELAY_ACTIVE_HIGH = True

PIN_TM_CLK = 17
PIN_TM_DIO = 16

PIN_I2C_SDA = 21
PIN_I2C_SCL = 22
LCD_I2C_ADDR = 0x27

# Logic thresholds
ENTRY_DISTANCE_CM = 12
GATE_OPEN_ANGLE = 90
GATE_CLOSE_ANGLE = 0
GATE_OPEN_MS = 3500

# Timing (ms)
SENSOR_SCAN_MS = 200
DISPLAY_REFRESH_MS = 1200
TELEGRAM_POLL_MS = 2000
BLYNK_POLL_MS = 1200
BLYNK_PUSH_MS = 4000
AUTO_LIGHT_TIMEOUT_MS = 30000


# =========================
# TM1637 DRIVER
# =========================
CMD_DATA = 0x40
CMD_ADDR = 0xC0
CMD_CTRL = 0x80

SEGMENTS = [
    0x3F, 0x06, 0x5B, 0x4F, 0x66,
    0x6D, 0x7D, 0x07, 0x7F, 0x6F
]


class TM1637:
    def __init__(self, clk_pin, dio_pin, brightness=5):
        self.clk = Pin(clk_pin, Pin.OUT, value=1)
        self.dio = Pin(dio_pin, Pin.OUT, value=1)
        self.brightness = max(0, min(brightness, 7))
        self._update_display()

    def _start(self):
        self.dio.value(0)
        time.sleep_us(10)
        self.clk.value(0)

    def _stop(self):
        self.clk.value(1)
        time.sleep_us(10)
        self.dio.value(1)

    def _write_byte(self, data):
        for _ in range(8):
            self.dio.value(data & 0x01)
            data >>= 1
            self.clk.value(1)
            time.sleep_us(10)
            self.clk.value(0)
        self.clk.value(1)
        time.sleep_us(10)
        self.clk.value(0)

    def _update_display(self):
        self._start()
        self._write_byte(CMD_CTRL | 0x08 | self.brightness)
        self._stop()

    def show_digit(self, number):
        if number < 0:
            number = 0
        if number > 9999:
            number = 9999

        text = str(number)
        data = [0x00, 0x00, 0x00, 0x00]
        start = 4 - len(text)
        for i, ch in enumerate(text):
            data[start + i] = SEGMENTS[int(ch)]

        self._start()
        self._write_byte(CMD_DATA)
        self._stop()

        self._start()
        self._write_byte(CMD_ADDR)
        for seg in data:
            self._write_byte(seg)
        self._stop()

        self._update_display()


# =========================
# LCD I2C
# =========================
LCD_CLR = 0x01
LCD_HOME = 0x02
LCD_ENTRY_MODE = 0x04
LCD_ENTRY_INC = 0x02
LCD_ON_CTRL = 0x08
LCD_ON_DISPLAY = 0x04
LCD_FUNCTION = 0x20
LCD_FUNCTION_2L = 0x08
LCD_SET_DDRAM = 0x80

MASK_RS = 0x01
MASK_E = 0x04
MASK_BL = 0x08


class LcdApi:
    def __init__(self, num_lines, num_columns):
        self.num_lines = num_lines
        self.num_columns = num_columns
        self.cursor_x = 0
        self.cursor_y = 0

    def clear(self):
        self.hal_write_command(LCD_CLR)
        time.sleep_ms(2)
        self.move_to(0, 0)

    def move_to(self, col, row):
        self.cursor_x = col
        self.cursor_y = row
        addr = col & 0x3F
        if row == 1:
            addr |= 0x40
        elif row == 2:
            addr |= 0x14
        elif row == 3:
            addr |= 0x54
        self.hal_write_command(LCD_SET_DDRAM | addr)

    def putchar(self, char):
        if char == "\n":
            self.cursor_y = (self.cursor_y + 1) % self.num_lines
            self.move_to(0, self.cursor_y)
        else:
            self.hal_write_data(ord(char))
            self.cursor_x += 1
            if self.cursor_x >= self.num_columns:
                self.cursor_x = 0
                self.cursor_y = (self.cursor_y + 1) % self.num_lines
                self.move_to(self.cursor_x, self.cursor_y)

    def putstr(self, text):
        for char in text:
            self.putchar(char)

    def hal_write_command(self, cmd):
        raise NotImplementedError

    def hal_write_data(self, data):
        raise NotImplementedError


class I2cLcd(LcdApi):
    def __init__(self, i2c, i2c_addr, num_lines, num_columns, backlight=True):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.backlight = MASK_BL if backlight else 0
        self._byte(0)

        self._write_init_nibble(0x30)
        self._write_init_nibble(0x30)
        self._write_init_nibble(0x30)
        self._write_init_nibble(0x20)

        func = LCD_FUNCTION | (LCD_FUNCTION_2L if num_lines > 1 else 0)
        self.hal_write_command(func)
        self.hal_write_command(LCD_ON_CTRL | LCD_ON_DISPLAY)
        self.hal_write_command(LCD_ENTRY_MODE | LCD_ENTRY_INC)
        super().__init__(num_lines, num_columns)
        self.clear()

    def hal_write_command(self, cmd):
        self._write4(cmd, False)

    def hal_write_data(self, data):
        self._write4(data, True)

    def _write_init_nibble(self, nibble):
        self._nibble(nibble)
        self._strobe()

    def _write4(self, value, rs):
        high = value & 0xF0
        low = (value << 4) & 0xF0
        self._nibble(high, rs)
        self._strobe()
        self._nibble(low, rs)
        self._strobe()

    def _nibble(self, nib, rs=False):
        data = (nib & 0xF0) | (MASK_RS if rs else 0) | self.backlight
        self._byte(data)

    def _strobe(self):
        self._byte(self._last | MASK_E)
        time.sleep_us(1)
        self._byte(self._last & ~MASK_E)
        time.sleep_us(50)

    def _byte(self, value):
        self._last = value
        self.i2c.writeto(self.i2c_addr, bytes([value]))


# =========================
# GLOBAL HARDWARE
# =========================
ultra_trig = Pin(PIN_TRIG, Pin.OUT)
ultra_echo = Pin(PIN_ECHO, Pin.IN)

slot_sensors = [Pin(pin, Pin.IN) for pin in PIN_IR_SLOTS]

servo = PWM(Pin(PIN_SERVO), freq=50)
dht_sensor = dht.DHT11(Pin(PIN_DHT))
relay = Pin(PIN_RELAY, Pin.OUT)

tm = TM1637(clk_pin=PIN_TM_CLK, dio_pin=PIN_TM_DIO, brightness=5)

i2c = SoftI2C(sda=Pin(PIN_I2C_SDA), scl=Pin(PIN_I2C_SCL), freq=400000)
lcd = I2cLcd(i2c, LCD_I2C_ADDR, 2, 16)


# =========================
# STATE
# =========================
slots_total = len(slot_sensors)
slots_occupied = 0
slots_available = slots_total

gate_open = False
gate_close_deadline = 0
entry_latch = False

relay_manual_override = None  # None=auto, True=force on, False=force off
relay_auto_hold_until = 0

last_temp = None
last_hum = None
last_distance = None

telegram_offset = 0

last_sensor_ms = 0
last_display_ms = 0
last_tg_ms = 0
last_blynk_poll_ms = 0
last_blynk_push_ms = 0


# =========================
# HELPERS
# =========================
def now_ms():
    return time.ticks_ms()


def ticks_passed(current, previous):
    return time.ticks_diff(current, previous)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    print("Connecting WiFi...")
    timeout = 25
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1

    if not wlan.isconnected():
        raise RuntimeError("WiFi connection failed")

    print("WiFi connected:", wlan.ifconfig())
    return wlan


def sync_ntp_time():
    try:
        ntptime.settime()
        print("NTP synced")
    except Exception as exc:
        print("NTP sync skipped:", exc)


def url_encode(text):
    out = []
    for value in str(text).encode("utf-8"):
        if (48 <= value <= 57) or (65 <= value <= 90) or (97 <= value <= 122) or value in b"-_.~":
            out.append(chr(value))
        elif value == 32:
            out.append("+")
        else:
            out.append("%{:02X}".format(value))
    return "".join(out)


def http_get_json(url):
    response = None
    try:
        response = urequests.get(url)
        return response.json()
    except Exception as exc:
        print("GET JSON failed:", exc)
        return None
    finally:
        if response:
            response.close()


def http_get_text(url):
    response = None
    try:
        response = urequests.get(url)
        return response.text
    except Exception as exc:
        print("GET text failed:", exc)
        return None
    finally:
        if response:
            response.close()


def telegram_send(text, chat_id=None):
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    url = "https://api.telegram.org/bot{}/sendMessage".format(TELEGRAM_BOT_TOKEN)
    payload = "chat_id={}&text={}".format(url_encode(chat_id), url_encode(text))
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = None
    try:
        response = urequests.post(url, data=payload, headers=headers)
    except Exception as exc:
        print("Telegram send failed:", exc)
    finally:
        if response:
            response.close()


def blynk_update(vpin, value):
    url = "{}/update?token={}&{}={}".format(BLYNK_API, BLYNK_TOKEN, vpin, url_encode(value))
    response = None
    try:
        response = urequests.get(url)
    except Exception as exc:
        print("Blynk update failed:", exc)
    finally:
        if response:
            response.close()


def blynk_get(vpin, default=0):
    url = "{}/get?token={}&{}".format(BLYNK_API, BLYNK_TOKEN, vpin)
    raw = http_get_text(url)
    if raw is None:
        return default
    try:
        return int(str(raw).strip().strip('[]"'))
    except Exception:
        return default


def read_distance_cm():
    ultra_trig.value(0)
    time.sleep_us(2)
    ultra_trig.value(1)
    time.sleep_us(10)
    ultra_trig.value(0)

    duration = time_pulse_us(ultra_echo, 1, 30000)
    if duration < 0:
        return None
    return round((duration * 0.0343) / 2, 2)


def read_temp_hum():
    try:
        dht_sensor.measure()
        return dht_sensor.temperature(), dht_sensor.humidity()
    except Exception as exc:
        print("DHT read failed:", exc)
        return None, None


def relay_on():
    relay.value(1 if RELAY_ACTIVE_HIGH else 0)


def relay_off():
    relay.value(0 if RELAY_ACTIVE_HIGH else 1)


def relay_is_on():
    expected = 1 if RELAY_ACTIVE_HIGH else 0
    return relay.value() == expected


def servo_write_angle(angle):
    if angle < 0:
        angle = 0
    if angle > 180:
        angle = 180

    corrected = 180 - angle
    duty = int((corrected / 180) * 102 + 26)
    servo.duty(duty)


def open_gate(source="AUTO"):
    global gate_open, gate_close_deadline
    servo_write_angle(GATE_OPEN_ANGLE)
    gate_open = True
    gate_close_deadline = time.ticks_add(now_ms(), GATE_OPEN_MS)
    print("Gate opened by", source)


def close_gate(source="AUTO"):
    global gate_open, gate_close_deadline
    servo_write_angle(GATE_CLOSE_ANGLE)
    gate_open = False
    gate_close_deadline = 0
    print("Gate closed by", source)


def slots_text():
    return "Slots: {}/{} available".format(slots_available, slots_total)


def status_text():
    temp = "--" if last_temp is None else "{}C".format(last_temp)
    hum = "--" if last_hum is None else "{}%".format(last_hum)
    gate = "OPEN" if gate_open else "CLOSED"
    light = "ON" if relay_is_on() else "OFF"
    return "🚗 Smart Parking\n{}\n🌡 {} 💧 {}\n🚧 {} | 💡 {}".format(slots_text(), temp, hum, gate, light)


def refresh_slot_count():
    global slots_occupied, slots_available
    occupied = 0
    for sensor in slot_sensors:
        if sensor.value() == 0:
            occupied += 1
    slots_occupied = occupied
    slots_available = slots_total - slots_occupied


def update_light_logic():
    current = now_ms()

    if relay_manual_override is True:
        relay_on()
        return

    if relay_manual_override is False:
        relay_off()
        return

    # Auto mode
    hold_active = time.ticks_diff(relay_auto_hold_until, current) > 0

    if slots_occupied > 0 or hold_active:
        relay_on()
    else:
        relay_off()


def touch_light_auto_timer():
    global relay_auto_hold_until
    relay_auto_hold_until = time.ticks_add(now_ms(), AUTO_LIGHT_TIMEOUT_MS)


def update_lcd():
    line1 = "Avl:{}/{} {}".format(slots_available, slots_total, "OPEN" if gate_open else "CLOSE")
    if last_temp is None or last_hum is None:
        line2 = "T:-- H:-- L:{}".format("ON" if relay_is_on() else "OFF")
    else:
        line2 = "T:{} H:{} L:{}".format(last_temp, last_hum, "ON" if relay_is_on() else "OFF")

    lcd.clear()
    lcd.move_to(0, 0)
    row1 = line1[:16]
    if len(row1) < 16:
        row1 = row1 + (" " * (16 - len(row1)))
    lcd.putstr(row1)
    lcd.move_to(0, 1)
    row2 = line2[:16]
    if len(row2) < 16:
        row2 = row2 + (" " * (16 - len(row2)))
    lcd.putstr(row2)


def update_tm1637():
    tm.show_digit(slots_available)


def web_page():
    temp = "--" if last_temp is None else str(last_temp)
    gate = "OPEN" if gate_open else "CLOSED"
    light = "ON" if relay_is_on() else "OFF"

    return """HTTP/1.1 200 OK
Content-Type: text/html

<html>
<head>
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<meta http-equiv=\"refresh\" content=\"3\" />
<title>Smart IoT Parking</title>
<style>
body { font-family: Arial; text-align:center; background:#f2f2f2; margin-top:24px; }
.card { background:white; max-width:360px; margin:auto; padding:18px; border-radius:12px; }
button { width:140px; height:42px; margin:5px; border:none; border-radius:8px; color:white; }
.green { background:#28a745; } .red { background:#dc3545; } .blue { background:#007bff; } .gray { background:#6c757d; }
</style>
</head>
<body>
<div class=\"card\">
<h2>Smart Parking</h2>
<p><b>Available Slots:</b> {slots}</p>
<p><b>Temperature:</b> {temp} C</p>
<p><b>Gate Status:</b> {gate}</p>
<p><b>Relay Status:</b> {light}</p>
<a href=\"/open\"><button class=\"green\">Open Gate</button></a>
<a href=\"/close\"><button class=\"red\">Close Gate</button></a><br/>
<a href=\"/light_on\"><button class=\"blue\">Light ON</button></a>
<a href=\"/light_off\"><button class=\"gray\">Light OFF</button></a>
</div>
</body>
</html>
""".format(slots=slots_text(), temp=temp, gate=gate, light=light)


def process_web_request(raw_request):
    global relay_manual_override

    if not raw_request:
        return

    first_line = raw_request.split("\r\n")[0]

    if "GET /open" in first_line:
        if slots_available > 0:
            open_gate("WEB")
            touch_light_auto_timer()
        else:
            print("WEB open denied: parking full")

    elif "GET /close" in first_line:
        close_gate("WEB")

    elif "GET /light_on" in first_line:
        relay_manual_override = True
        relay_on()

    elif "GET /light_off" in first_line:
        relay_manual_override = False
        relay_off()


def poll_telegram_commands():
    global telegram_offset, relay_manual_override

    url = "https://api.telegram.org/bot{}/getUpdates?offset={}&timeout=0".format(
        TELEGRAM_BOT_TOKEN, telegram_offset
    )
    data = http_get_json(url)

    if not data:
        print("Telegram: no response")
        return

    if not data.get("ok"):
        print("Telegram response not ok:", data)
        return

    for update in data.get("result", []):
        telegram_offset = update.get("update_id", 0) + 1

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue

        chat_id = str((msg.get("chat") or {}).get("id", ""))
        raw_text = (msg.get("text") or "").strip().lower()

        print("Incoming chat_id:", chat_id)
        print("Raw Telegram text:", raw_text)

        if not raw_text:
            continue

        # Normalize commands:
        # /open
        # /open@YourBotName
        # /open something
        command = raw_text.split()[0]
        command = command.split("@")[0]

        print("Normalized command:", command)

        if chat_id != str(TELEGRAM_CHAT_ID):
            print("Ignored Telegram message: chat_id mismatch")
            continue

        if command == "/status":
            telegram_send(status_text(), chat_id)

        elif command == "/open":
            if slots_available > 0:
                open_gate("TELEGRAM")
                touch_light_auto_timer()
                telegram_send("🚧 Gate opened", chat_id)
            else:
                telegram_send("❌ Parking full. Gate remains closed.", chat_id)

        elif command == "/close":
            close_gate("TELEGRAM")
            telegram_send("🚧 Gate closed", chat_id)

        elif command == "/slots":
            telegram_send("🅿️ " + slots_text(), chat_id)

        elif command == "/temp":
            if last_temp is None or last_hum is None:
                telegram_send("🌡 Temperature/Humidity unavailable", chat_id)
            else:
                telegram_send("🌡 {} C\n💧 {} %".format(last_temp, last_hum), chat_id)

        elif command == "/light_on":
            relay_manual_override = True
            relay_on()
            telegram_send("💡 Light forced ON (manual mode)", chat_id)

        elif command == "/light_off":
            relay_manual_override = False
            relay_off()
            telegram_send("💡 Light forced OFF (manual mode)", chat_id)

        else:
            print("Unknown Telegram command:", command)


def poll_blynk_controls():
    servo_button = blynk_get("V0", 0)

    if servo_button == 1:
        if slots_available > 0:
            open_gate("BLYNK")
            touch_light_auto_timer()
        else:
            close_gate("BLYNK")
    else:
        if gate_open:
            close_gate("BLYNK")


def push_blynk_data():
    blynk_update("V1", last_temp if last_temp is not None else 0)
    blynk_update("V2", slots_available)
    blynk_update("V3", 1 if gate_open else 0)
    blynk_update("V4", 1 if relay_is_on() else 0)


def scan_sensors_and_logic():
    global last_temp, last_hum, last_distance, entry_latch

    refresh_slot_count()

    last_distance = read_distance_cm()
    last_temp, last_hum = read_temp_hum()

    detected = (last_distance is not None) and (last_distance <= ENTRY_DISTANCE_CM)

    if detected and not entry_latch:
        if slots_available > 0 and not gate_open:
            open_gate("ULTRASONIC")
            touch_light_auto_timer()
        elif slots_available <= 0:
            print("Vehicle detected but parking full")
        entry_latch = True
    elif not detected:
        entry_latch = False

    if gate_open and gate_close_deadline and ticks_passed(now_ms(), gate_close_deadline) >= 0:
        close_gate("AUTO-TIMER")

    update_light_logic()


def boot_banner():
    lcd.clear()
    lcd.move_to(0, 0)
    lcd.putstr("Smart Parking")
    lcd.move_to(0, 1)
    lcd.putstr("Booting...")


def init_system_defaults():
    global relay_manual_override
    relay_manual_override = None
    close_gate("INIT")
    relay_off()
    refresh_slot_count()
    update_tm1637()
    update_lcd()


def run():
    global last_sensor_ms, last_display_ms, last_tg_ms, last_blynk_poll_ms, last_blynk_push_ms

    boot_banner()
    connect_wifi()
    sync_ntp_time()
    init_system_defaults()

    addr = socket.getaddrinfo("0.0.0.0", 8080)[0][-1]
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(1)
    server.settimeout(0.1)

    print("Web dashboard: http://<esp32-ip>:8080")
    print("Telegram commands ready: /status /open /close /slots /temp /light_on /light_off")

    while True:
        current = now_ms()

        try:
            client, _ = server.accept()
            req = client.recv(1024)
            text = req.decode() if req else ""
            process_web_request(text)
            client.send(web_page())
            client.close()
        except OSError:
            pass
        except Exception as exc:
            print("Web error:", exc)

        if ticks_passed(current, last_sensor_ms) >= SENSOR_SCAN_MS:
            last_sensor_ms = current
            scan_sensors_and_logic()

        if ticks_passed(current, last_display_ms) >= DISPLAY_REFRESH_MS:
            last_display_ms = current
            update_tm1637()
            update_lcd()

        if ticks_passed(current, last_tg_ms) >= TELEGRAM_POLL_MS:
            last_tg_ms = current
            poll_telegram_commands()

        if ticks_passed(current, last_blynk_poll_ms) >= BLYNK_POLL_MS:
            last_blynk_poll_ms = current
            poll_blynk_controls()

        if ticks_passed(current, last_blynk_push_ms) >= BLYNK_PUSH_MS:
            last_blynk_push_ms = current
            push_blynk_data()

        time.sleep_ms(30)


if __name__ == "__main__":
    run()
