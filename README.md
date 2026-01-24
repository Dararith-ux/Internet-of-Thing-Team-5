
# ESP32 Telegram-Controlled Relay with DHT22

This project uses an ESP32 microcontroller to read temperature and humidity from a DHT22 sensor and control a relay module via Telegram commands.

---

## 🔌 Wiring Diagram / Hardware Connections

### Components Used
- ESP32 Dev Module (ESP32-WROOM-32)
- DHT22 Temperature & Humidity Sensor
- 1-Channel 5V Relay Module
- Jumper wires
- (Optional) Breadboard

### Wiring Connections

#### DHT22 → ESP32
| DHT22 Pin | ESP32 Pin |
|----------|-----------|
| VCC | 3V3 |
| DATA | GPIO 4 |
| GND | GND |

#### Relay Module → ESP32
| Relay Pin | ESP32 Pin |
|----------|-----------|
| VCC | 5V (VIN) |
| GND | GND |
| IN | GPIO 15 |

> 📌 Note: All components share a **common GND**.

📷 *Insert wiring diagram or photo here (Wokwi or real hardware image).*

---

## ⚙️ Configuration Steps

### 1. Telegram Bot Setup
1. Create a Telegram bot using **@BotFather**
2. Copy the generated **Bot Token**
3. Add the bot to your Telegram group
4. Get the **Group Chat ID**

### 2. Code Configuration
Update the following values in the code:

```cpp
#define BOT_TOKEN "YOUR_BOT_TOKEN"
#define CHAT_ID "YOUR_GROUP_CHAT_ID"
#define DHTPIN 4
#define RELAY_PIN 15
````

### 3. Wi-Fi Credentials

```cpp
const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";
```

---

## ▶️ Usage Instructions

1. Power the ESP32 via USB
2. ESP32 connects to Wi-Fi
3. ESP32 connects to Telegram bot
4. Use the following commands in Telegram:

| Command   | Description                                 |
| --------- | ------------------------------------------- |
| `/status` | Get temperature, humidity, and relay status |
| `/on`     | Turn relay ON                               |
| `/off`    | Turn relay OFF                              |

> If the relay is OFF, temperature and humidity are not displayed.

---

## 🔁 Program Flow / Block Diagram

### System Flowchart

```
START
  |
  v
Initialize ESP32
(WiFi, Telegram, DHT22, Relay)
  |
  v
Connect to WiFi
  |
  v
Check Telegram Messages
  |
  v
Is command received?
  |        \
 NO         YES
  |          |
  |     Process Command
  |     (/on, /off, /status)
  |          |
  |     Control Relay
  |     Read DHT22 (if relay ON)
  |          |
  \----------/
       |
       v
     Delay
       |
       v
     LOOP
```

---

## ✅ Notes

* Relay uses **5V** because it requires higher power for the coil.
* DHT22 uses **3.3V** to match ESP32 GPIO logic levels.
* GPIO 4 and GPIO 15 are safe, commonly used pins for ESP32.

---

## 📌 Author

ESP32 IoT Project – Telegram Bot Control

