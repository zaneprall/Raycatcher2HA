#!/command/with-contenv bashio
set -euo pipefail

# ---- Read options ----
MQTT_HOST="$(bashio::config 'mqtt_host')"
MQTT_PORT="$(bashio::config 'mqtt_port')"
MQTT_USER="$(bashio::config 'mqtt_user')"
MQTT_PASS="$(bashio::config 'mqtt_pass')"

POLL_INTERVAL="$(bashio::config 'poll_interval')"
HTTP_TIMEOUT="$(bashio::config 'http_timeout')"
HTTP_RETRIES="$(bashio::config 'http_retries')"
HTTP_BACKOFF_BASE="$(bashio::config 'http_backoff_base')"

DEVICE_ID="$(bashio::config 'device_id')"
DEVICE_NAME="$(bashio::config 'device_name')"
ADB_SERIAL="$(bashio::config 'adb_serial')"

ALERT_ON_NEW="$(bashio::config 'alert_on_new')"
FORCE_ALERT_SECS="$(bashio::config 'force_alert_secs')"
AUTOCLEAR_SECS="$(bashio::config 'autoclear_secs')"

export RAYHUNTER_BASE="http://127.0.0.1:18080"
export DISCOVERY_PREFIX="homeassistant"
export DEVICE_ID DEVICE_NAME
export POLL_INTERVAL="$POLL_INTERVAL"
export HTTP_TIMEOUT HTTP_RETRIES HTTP_BACKOFF_BASE
export AUTOCLEAR_SECS FORCE_ALERT_SECS
if [[ -n "$MQTT_HOST" ]]; then
  export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASS
fi
if [[ "$ALERT_ON_NEW" == "true" ]]; then export ALERT_ON_NEW=1; fi

# ---- ADB setup / keep-forward loop ----
adb start-server
bashio::log.info "ADB server started"

# helper prints device list for logs
adb devices -l || true

# background: maintain tcp:18080 -> tcp:8080
keep_forward() {
  while true; do
    if [[ -n "$ADB_SERIAL" ]]; then
      # wait for device; don't block forever
      adb -s "$ADB_SERIAL" wait-for-device || true
      # ensure mapping exists
      if ! adb -s "$ADB_SERIAL" forward --list | grep -q 'tcp:18080'; then
        adb -s "$ADB_SERIAL" forward --remove-all || true
        adb -s "$ADB_SERIAL" forward tcp:18080 tcp:8080 || true
        bashio::log.info "Port-forward established (serial=$ADB_SERIAL)"
      fi
    else
      # single-device path
      if ! adb forward --list | grep -q 'tcp:18080'; then
        adb forward --remove-all || true
        adb forward tcp:18080 tcp:8080 || true
        bashio::log.info "Port-forward established"
      fi
    fi
    sleep 5
  done
}

keep_forward &

# ---- Start bridge ----
exec python3 /opt/rayhunter/rayhunter_bridge.py
