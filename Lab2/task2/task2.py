import network
import socket
import time
from machine import Pin, time_pulse_us
import dht

# ======================
# HARDWARE SETUP
# ======================
led = Pin(2, Pin.OUT)
led.off()

dht_sensor = dht.DHT11(Pin(4))

TRIG = Pin(27, Pin.OUT)
ECHO = Pin(26, Pin.IN)

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

ip = wifi.ifconfig()[0]
print("Connected")
print("ESP32 IP:", ip)

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
# WEB PAGE (THONNY SAFE)
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
<meta http-equiv="refresh" content="2">
<style>
body {{
    font-family: Arial;
    background-color: #eeeeee;
    text-align: center;
    margin-top: 60px;
}}

.card {{
    background-color: white;
    width: 320px;
    margin: auto;
    padding: 25px;
    border-radius: 10px;
}}

h1 {{
    margin-bottom: 20px;
}}

.data {{
    font-size: 18px;
    margin: 10px 0;
}}

button {{
    width: 120px;
    height: 45px;
    font-size: 16px;
    margin: 8px;
    border-radius: 6px;
    border: none;
}}

.on {{
    background-color: #4CAF50;
    color: white;
}}

.off {{
    background-color: #f44336;
    color: white;
}}
</style>
</head>

<body>
<div class="card">
<h1>ESP32 Dashboard</h1>

<div class="data">Temperature: <b>{temp} C</b></div>
<div class="data">Humidity: <b>{hum} %</b></div>
<div class="data">Distance: <b>{dist} cm</b></div>

<a href="/on"><button class="on">LED ON</button></a>
<a href="/off"><button class="off">LED OFF</button></a>
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

    if "/on" in request:
        led.on()
    elif "/off" in request:
        led.off()

    temp, hum = read_dht11()
    dist = get_distance_cm()

    client.send(webpage(temp, hum, dist))
    client.close()
