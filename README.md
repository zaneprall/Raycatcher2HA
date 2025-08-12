# Raycatcher2HA
Allows you to push rayhunter alerts to your home assistant devices




In the HA UI: Settings → Add-ons → Add-on Store → ••• → Repositories → add a local repository by picking the /addons folder in the file editor, then place this add-on at /addons/rayhunter-bridge/.

Open the add-on, Configure:

    mqtt_host: core-mosquitto (default) or your external broker host

    mqtt_user/mqtt_pass: if your broker requires auth

    leave adb_serial empty unless multiple Android devices are attached

Start the add-on. Logs should show:

    “ADB server started”

    “Port-forward established”

    periodic lines from the bridge: hb=ok last_id=... warnings=... alert=...

In Home Assistant: Settings → Devices & Services → MQTT → new device Rayhunter (Orbic) with:

    binary_sensor.rayhunter_alert

    sensor.rayhunter_last_report_id

    sensor.rayhunter_last_warning_count

If you want to see end-to-end immediately, enable a self-test in the add-on options:

    force_alert_secs: 30 and optionally autoclear_secs: 15
