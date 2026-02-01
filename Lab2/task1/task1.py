import network
import socket
from machine import Pin
import time

# ======================
# LED SETUP
# ======================
led = Pin(2, Pin.OUT)   # onboard LED
led.off()

# ======================
# WIFI SETUP (SAFE)
# ======================
SSID = "water"
PASSWORD = "shibalshibal"

wifi = network.WLAN(network.STA_IF)

# fully reset wifi driver
wifi.active(False)
time.sleep(1)
wifi.active(True)

print("Connecting to WiFi...")
wifi.connect(SSID, PASSWORD)

# wait with timeout
timeout = 15
while not wifi.isconnected() and timeout > 0:
    time.sleep(1)
    timeout -= 1

if not wifi.isconnected():
    print("WiFi FAILED — reset board and try again")
    raise SystemExit

ip = wifi.ifconfig()[0]
print("Connected!")
print("ESP32 IP:", ip)

# ======================
# WEB SERVER
# ======================
addr = socket.getaddrinfo("0.0.0.0", 8080)[0][-1]

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(addr)
server.listen(1)

print("Server running on port 8080")

# ======================
# HTML PAGE
# ======================
def webpage():
    return """\
HTTP/1.1 200 OK

<html>
<head>
<title>ESP32 LED Control</title>
<style>
body {
    font-family: Arial, sans-serif;
    background: #f2f2f2;
    text-align: center;
    margin-top: 80px;
}

.card {
    background: white;
    width: 300px;
    margin: auto;
    padding: 30px;
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

h1 {
    margin-bottom: 25px;
}

button {
    width: 120px;
    height: 50px;
    font-size: 18px;
    margin: 10px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
}

.on { background: #4CAF50; color: white; }
.off { background: #f44336; color: white; }

button:hover {
    opacity: 0.85;
}
</style>
</head>

<body>
<div class="card">
    <h1>ESP32 LED</h1>
    <a href="/on"><button class="on">ON</button></a>
    <a href="/off"><button class="off">OFF</button></a>
</div>
</body>
</html>
"""

# ======================
# MAIN LOOP
# ======================
while True:
    client, addr = server.accept()
    request = client.recv(1024).decode()

    print("Request:", request)

    if "/on" in request:
        led.on()
        print("LED ON")

    if "/off" in request:
        led.off()
        print("LED OFF")

    client.send(webpage())
    client.close()

