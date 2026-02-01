import network
import socket
import time
from machine import Pin, time_pulse_us, SoftI2C
import dht
from machine_i2c_lcd import I2cLcd

# ======================
# HARDWARE SETUP
# ======================
led = Pin(2, Pin.OUT)
led.off()

dht_sensor = dht.DHT11(Pin(4))

TRIG = Pin(27, Pin.OUT)
ECHO = Pin(26, Pin.IN)

# LCD 16x2
I2C_ADDR = 0x27
i2c = SoftI2C(sda=Pin(21), scl=Pin(22), freq=400000)
lcd = I2cLcd(i2c, I2C_ADDR, 2, 16)
lcd.clear()

# ======================
# WIFI SETUP
# ======================
SSID = "water"
PASSWORD = "shibalshibal"

wifi = network.WLAN(network.STA_IF)
wifi.active(False)
time.sleep(1)
wifi.active(True)

print("Connecting to WiFi...")
wifi.connect(SSID, PASSWORD)

timeout = 15
while not wifi.isconnected() and timeout > 0:
    time.sleep(1)
    timeout -= 1

if not wifi.isconnected():
    print("WiFi failed")
    raise SystemExit

print("Connected")
print("ESP32 IP:", wifi.ifconfig()[0])

# ======================
# SENSOR FUNCTIONS
# ======================
def read_dht11():
    try:
        dht_sensor.measure()
        return dht_sensor.temperature(), dht_sensor.humidity()
    except:
        return None, None

def get_distance_cm():
    TRIG.value(0)
    time.sleep_us(2)
    TRIG.value(1)
    time.sleep_us(10)
    TRIG.value(0)

    duration = time_pulse_us(ECHO, 1, 30000)
    if duration < 0:
        return None

    return round((duration * 0.0343) / 2, 2)

# ======================
# LCD FUNCTIONS
# ======================
def lcd_show_distance(distance):
    lcd.clear()
    lcd.move_to(0, 0)
    if distance is None:
        lcd.putstr("No distance")
    else:
        lcd.putstr("Dist: {} cm".format(distance))

def lcd_show_temperature(temp):
    lcd.clear()
    lcd.move_to(0, 1)
    if temp is None:
        lcd.putstr("No temp")
    else:
        lcd.putstr("Temp: {} C".format(temp))

def lcd_scroll_text(text):
    lcd.clear()

    if len(text) <= 16:
        lcd.move_to(0, 0)
        lcd.putstr(text)
        return

    padded = text + " " * 16
    for i in range(len(padded) - 15):
        lcd.move_to(0, 0)
        lcd.putstr(padded[i:i+16])
        time.sleep(0.3)

# ======================
# WEB PAGE (NO AUTO REFRESH)
# ======================
def webpage(temp, hum, dist):

    if temp is None:
        temp = "--"
    if hum is None:
        hum = "--"
    if dist is None:
        dist = "--"

    return f"""HTTP/1.1 200 OK
Content-Type: text/html

<html>
<head>
<title>ESP32 Dashboard</title>
<style>
body {{
    font-family: Arial;
    background-color: #eeeeee;
    text-align: center;
    margin-top: 50px;
}}

.card {{
    background-color: white;
    width: 360px;
    margin: auto;
    padding: 25px;
    border-radius: 10px;
}}

button {{
    width: 160px;
    height: 40px;
    font-size: 16px;
    margin: 6px;
    border-radius: 6px;
    border: none;
}}

.green {{ background-color: #4CAF50; color: white; }}
.blue {{ background-color: #2196F3; color: white; }}
.orange {{ background-color: #FF9800; color: white; }}
</style>
</head>

<body>
<div class="card">
<h2>ESP32 Dashboard</h2>

<p>Temperature: {temp} C</p>
<p>Humidity: {hum} %</p>
<p>Distance: {dist} cm</p>

<a href="/show_distance"><button class="blue">Show Distance</button></a><br>
<a href="/show_temp"><button class="orange">Show Temp</button></a><br><br>

<form action="/send">
<input type="text" name="msg" style="width:90%;height:35px">
<br>
<button class="green" type="submit">Send</button>
</form>

</div>
</body>
</html>
"""

# ======================
# WEB SERVER
# ======================
addr = socket.getaddrinfo("0.0.0.0", 8080)[0][-1]
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(addr)
server.listen(1)

print("Web server running on port 8080")

# ======================
# MAIN LOOP
# ======================
while True:
    client, addr = server.accept()
    request = client.recv(1024).decode()

    temp, hum = read_dht11()
    dist = get_distance_cm()

    if "/show_distance" in request:
        lcd_show_distance(dist)

    elif "/show_temp" in request:
        lcd_show_temperature(temp)

    elif request.startswith("GET /send?"):
        try:
            # Only take the first request line
            first_line = request.split("\r\n")[0]

            # Extract msg value
            query = first_line.split("msg=")[1]
            msg = query.split(" ")[0]

            # Basic URL decoding
            msg = msg.replace("+", " ")
            msg = msg.replace("%20", " ")

            lcd_scroll_text(msg)
        except:
            pass

    client.send(webpage(temp, hum, dist))
    client.close()
