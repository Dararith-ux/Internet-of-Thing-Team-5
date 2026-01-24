
# ESP32 Telegram-Controlled Relay with DHT22

This project uses an ESP32 microcontroller to read temperature and humidity from a DHT11 sensor and control a relay module via Telegram commands.

---

## 🔌 Wiring Diagram / Hardware Connections

### Components Used
- ESP32 Dev Module (ESP32-WROOM-32)
- ESP32 Expansion Board
- DHT11 Temperature & Humidity Sensor
- 1-Channel 5V Relay Module
- Jumper wires

### Wiring Connections

#### DHT11 → ESP32
| DHT11 Pin | ESP32 Pin |
|----------|-----------|
| VCC (+) | VCC/3V3 |
| DATA (I/O) | GPIO 4 |
| GND (-) | GND |

#### Relay Module → ESP32
| Relay Pin | ESP32 Pin |
|----------|-----------|
| VCC | VCC/5V (VIN) |
| GND | GND |
| IN | GPIO 2 |

![Wiring Diagram](/wiring.jpg)

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
#define RELAY_PIN 2
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
![System Flowchart](/systemflowchart.png)

---

## 📌 Author

ESP32 IoT Project Team 5 – Telegram Bot Control

