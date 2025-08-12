# Rayhunter Bridge Add-on for Home Assistant OS

This add-on connects an **Orbic Rayhunter** device to **Home Assistant** over USB, using `adb` port-forwarding to pull live system statistics from the Rayhunter's internal API and publish them via MQTT.

It is designed to run directly on **Home Assistant OS** (I used a Raspberry Pi 4) as a supervised add-on. It requires a wired USB connection to the Rayhunter device and an MQTT broker (e.g., the official `core-mosquitto` add-on).

---

## Features

- Automatic `adb` port-forwarding (`tcp:18080 → tcp:8080`) to the Rayhunter's local API.
- Polls `/api/system-stats` for real-time warning counts.
- Publishes state and binary sensor entities to MQTT for discovery in Home Assistant.
- MQTT Last Will & Testament (LWT) for entity availability.
- Optional alert debouncing, forced alerts, and auto-clear timers.
- Runs entirely as a Home Assistant OS add-on — no host modifications required.

---

## Installation

1. **Clone or copy this repository** into your Home Assistant OS add-ons folder: /addons/rayhunter-bridge/

2. In the HA UI:
- Go to **Settings → Add-ons → Add-on Store → ••• → Repositories**.
- Add the local path containing this repository.

3. Open the **Rayhunter Bridge** add-on and click **Install**.

---

## Configuration

| Option              | Type   | Default           | Description |
|---------------------|--------|-------------------|-------------|
| `mqtt_host`         | str    | `core-mosquitto`  | MQTT broker hostname/IP. |
| `mqtt_port`         | int    | `1883`            | MQTT broker port. |
| `mqtt_user`         | str    | *(empty)*         | MQTT username. |
| `mqtt_pass`         | str    | *(empty)*         | MQTT password. |
| `poll_interval`     | int    | `3`               | Seconds between API polls. |
| `http_timeout`      | float  | `3`               | HTTP request timeout (seconds). |
| `http_retries`      | int    | `3`               | Retries before giving up. |
| `http_backoff_base` | float  | `0.4`             | Backoff multiplier between retries. |
| `device_id`         | str    | `rayhunter_orbic` | Device ID for MQTT discovery. |
| `device_name`       | str    | `Rayhunter (Orbic)` | Display name in HA. |
| `adb_serial`        | str    | *(empty)*         | Optional, only needed if multiple Android devices are connected. |
| `alert_on_new`      | bool   | `false`           | | If enabled, the add-on will trigger binary_sensor.rayhunter_alert only when the warningCount from /api/system-stats increases compared to the last poll. Does not mean “new file” or “new report ID.”  |
| `force_alert_secs`  | int    | `0`               | Force alert active if last change was within this many seconds. |
| `autoclear_secs`    | int    | `0`               | Automatically clear alert after this many seconds. |

---

## USB Access

Make sure your Rayhunter is connected via USB and **USB Debugging** is enabled. The add-on runs `adb start-server` automatically and will keep the port-forward alive.

---

## Home Assistant Entities

After install and configuration, you’ll see:
- `binary_sensor.rayhunter_alert` — active when alert is triggered.
- `sensor.rayhunter_last_report_id` — last processed report ID.
- `sensor.rayhunter_last_warning_count` — most recent warning count.

Entities are auto-discovered via MQTT.

---

## Development

Build locally for HA OS:
```bash
docker build -t local/rayhunter-bridge .
