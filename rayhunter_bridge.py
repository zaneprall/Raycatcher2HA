#!/usr/bin/env python3
"""
Rayhunter → Home Assistant bridge (HA OS add-on friendly).

Signals:
  - Alert when warnings > 0 (preferred).
  - Optionally alert when last_report_id changes (ALERT_ON_NEW=1).
  - Synthetic triggers for testing: FORCE_ALERT_SECS / stdin (when TTY).

Endpoints observed (best-effort):
  - /api/system-stats            -> warningCount, lastReportId (preferred)
  - /api/qmdl-manifest           -> list of analyses (fallback)
  - /api/analysis-report/<id>    -> full details (fallback)
"""
from __future__ import annotations
import json, os, sys, time, re, random, signal, threading, queue
from typing import Any, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# -------------------- Config --------------------
BASE = os.getenv("RAYHUNTER_BASE", "http://127.0.0.1:18080").rstrip("/")
POLL = int(os.getenv("POLL_INTERVAL", "3"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "3"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
HTTP_BACKOFF_BASE = float(os.getenv("HTTP_BACKOFF_BASE", "0.4"))

ALERT_ON_NEW = os.getenv("ALERT_ON_NEW", "0") == "1"
FORCE_ALERT_SECS = int(os.getenv("FORCE_ALERT_SECS", "0"))
AUTOCLEAR_SECS = int(os.getenv("AUTOCLEAR_SECS", "0"))

MQTT_ENABLED = bool(os.getenv("MQTT_HOST"))
MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))
MQTT_RETAIN = os.getenv("MQTT_RETAIN", "1") != "0"
DEVICE_ID = os.getenv("DEVICE_ID", "rayhunter_orbic")
DEVICE_NAME = os.getenv("DEVICE_NAME", "Rayhunter (Orbic)")
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant").strip("/")
AVAIL_SUFFIX = os.getenv("AVAIL_TOPIC_SUFFIX", "availability").strip("/")

# -------------------- HTTP with retries --------------------
def _sleep_backoff(attempt: int) -> None:
    base = HTTP_BACKOFF_BASE * (2 ** max(0, attempt - 1))
    time.sleep(min(5.0, base + random.uniform(0, base / 2)))

def http_get_text(path: str) -> Optional[str]:
    url = f"{BASE}{path}"
    req = Request(url, headers={"User-Agent": "rayhunter-bridge"})
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            with urlopen(req, timeout=HTTP_TIMEOUT) as r:
                return r.read().decode("utf-8", "ignore")
        except (HTTPError, URLError):
            if attempt >= HTTP_RETRIES:
                return None
            _sleep_backoff(attempt)
    return None

def json_get(path: str) -> Optional[Any]:
    txt = http_get_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None

# -------------------- Stats / Manifest helpers --------------------
def get_stats() -> Tuple[Optional[int], Optional[str]]:
    """Return (warning_count, last_report_id) from system-stats if available."""
    js = json_get("/api/system-stats")
    if not isinstance(js, dict):
        return None, None
    warn = js.get("warningCount") or js.get("warnings") or js.get("warning_count")
    lrid = js.get("lastReportId") or js.get("last_report_id") or js.get("last_id")
    try:
        warn = int(warn)
    except Exception:
        warn = None
    if lrid is not None:
        lrid = str(lrid)
    return warn, lrid

def parse_newest_entry(manifest: Any) -> Tuple[Optional[dict], Optional[str]]:
    if not isinstance(manifest, list) or not manifest:
        return None, None
    def _id(d: dict) -> Optional[int]:
        for k in ("id","report_id","reportId","uid"):
            v = d.get(k)
            if isinstance(v, bool):
                continue
            try:
                return int(v)
            except Exception:
                pass
        return None
    with_ids = [d for d in manifest if isinstance(d, dict) and _id(d) is not None]
    if with_ids:
        newest = max(with_ids, key=_id)  # type: ignore[arg-type]
        return newest, str(_id(newest))
    newest = manifest[-1] if isinstance(manifest[-1], dict) else None
    rid = None
    if newest:
        for k in ("id","report_id","reportId","uid"):
            if newest.get(k) is not None:
                rid = str(newest.get(k))
                break
    return newest, rid

def count_warnings_from_manifest_entry(entry: Optional[dict]) -> Optional[int]:
    if not isinstance(entry, dict):
        return None
    for k in ("warnings","warning_count","num_warnings","warningTotal"):
        v = entry.get(k)
        try:
            return max(0, int(v))
        except Exception:
            continue
    return None

def count_warnings_from_report(report: Any) -> int:
    if report is None:
        return 0
    if isinstance(report, dict):
        for k in ("warnings","warning_count","num_warnings","warningTotal","analysis.warnings","summary.warnings"):
            try:
                cur: Any = report
                for p in k.split("."):
                    cur = cur[p]  # type: ignore[index]
                return max(0, int(cur))
            except Exception:
                pass
    # Fallback heuristic: count nested 'severity' fields matching warn/critical
    def walk(x: Any) -> int:
        c = 0
        if isinstance(x, dict):
            sev = None
            for k,v in x.items():
                if isinstance(v,(dict,list)):
                    c += walk(v)
                elif isinstance(v,str) and k.lower() in ("severity","level","type","class"):
                    sev = v
            if sev and re.search(r"(warn|critical)", sev, re.I):
                c += 1
        elif isinstance(x, list):
            for i in x:
                c += walk(i)
        return c
    cnt = walk(report)
    if cnt: return cnt
    return len(re.findall(r"\bwarning\b", str(report), re.I))

# -------------------- MQTT --------------------
client = None
avail_topic = None
base_topic = None

def mqtt_setup():
    global client, avail_topic, base_topic
    if not MQTT_ENABLED:
        print("[mqtt] disabled (no MQTT_HOST)", flush=True)
        return
    import paho.mqtt.client as mqtt
    host = os.getenv("MQTT_HOST", "127.0.0.1")
    port = int(os.getenv("MQTT_PORT", "1883"))
    user = os.getenv("MQTT_USER", "")
    pw   = os.getenv("MQTT_PASS", "")

    c = mqtt.Client(client_id=f"{DEVICE_ID}_bridge", clean_session=True)
    avail = f"{DISCOVERY_PREFIX}/{DEVICE_ID}/{AVAIL_SUFFIX}"
    c.will_set(avail, payload="offline", qos=MQTT_QOS, retain=True)
    if user:
        c.username_pw_set(user, pw)
    c.connect(host, port, keepalive=max(30, POLL * 3))
    c.loop_start()

    device_meta = {
        "identifiers":[DEVICE_ID],
        "manufacturer":"EFF",
        "model":"Rayhunter",
        "name": DEVICE_NAME,
        "sw_version":"bridge-1.2",
    }
    alert_cfg = {
        "name":"Rayhunter Alert",
        "unique_id":f"{DEVICE_ID}_alert",
        "state_topic":f"{DISCOVERY_PREFIX}/{DEVICE_ID}/alert/state",
        "device_class":"safety",
        "availability_topic":avail,
        "payload_available":"online",
        "payload_not_available":"offline",
        "device":device_meta,
    }
    lastid_cfg = {
        "name":"Rayhunter Last Report ID",
        "unique_id":f"{DEVICE_ID}_lastid",
        "state_topic":f"{DISCOVERY_PREFIX}/{DEVICE_ID}/last_report_id/state",
        "availability_topic":avail,
        "payload_available":"online",
        "payload_not_available":"offline",
        "device":device_meta,
    }
    warn_cfg = {
        "name":"Rayhunter Last Warning Count",
        "unique_id":f"{DEVICE_ID}_lastwarn",
        "state_topic":f"{DISCOVERY_PREFIX}/{DEVICE_ID}/last_warning_count/state",
        "unit_of_measurement":"warnings",
        "availability_topic":avail,
        "payload_available":"online",
        "payload_not_available":"offline",
        "device":device_meta,
    }

    c.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/alert/config",
              json.dumps(alert_cfg), qos=MQTT_QOS, retain=True)
    c.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/last_report_id/config",
              json.dumps(lastid_cfg), qos=MQTT_QOS, retain=True)
    c.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/last_warning_count/config",
              json.dumps(warn_cfg), qos=MQTT_QOS, retain=True)
    c.publish(avail, "online", qos=MQTT_QOS, retain=True)

    client = c
    avail_topic = avail
    base_topic = f"{DISCOVERY_PREFIX}/{DEVICE_ID}"
    print("[mqtt] connected and discovery published", flush=True)

def mqtt_publish(state: Optional[bool], last_id: Optional[str], warn_count: Optional[int]):
    if not client:
        return
    if state is not None:
        client.publish(f"{base_topic}/alert/state", "ON" if state else "OFF", qos=MQTT_QOS, retain=MQTT_RETAIN)
    if last_id is not None:
        client.publish(f"{base_topic}/last_report_id/state", str(last_id), qos=MQTT_QOS, retain=MQTT_RETAIN)
    if warn_count is not None:
        client.publish(f"{base_topic}/last_warning_count/state", str(max(0,int(warn_count))), qos=MQTT_QOS, retain=MQTT_RETAIN)

def mqtt_teardown():
    if not client:
        return
    try:
        client.publish(avail_topic, "offline", qos=MQTT_QOS, retain=True)
        time.sleep(0.1)
        client.loop_stop()
        client.disconnect()
    except Exception:
        pass

# -------------------- stdin trigger (TTY only) --------------------
def start_stdin_trigger() -> Optional[queue.Queue]:
    if not sys.stdin.isatty():
        return None
    q: queue.Queue = queue.Queue()
    def _reader():
        try:
            for _ in sys.stdin: q.put(1)
        except Exception: pass
    threading.Thread(target=_reader, daemon=True).start()
    return q

# -------------------- Main loop --------------------
_shutdown = False
def _sigterm(_sig, _frm):
    global _shutdown
    _shutdown = True
signal.signal(signal.SIGINT, _sigterm)
signal.signal(signal.SIGTERM, _sigterm)

def main():
    mqtt_setup()
    stdin_q = start_stdin_trigger()

    last_warn = 0
    last_id = None
    last_alert = False
    last_line = ""
    next_forced = time.time() + FORCE_ALERT_SECS if FORCE_ALERT_SECS > 0 else 0
    clear_deadline = 0.0

    while not _shutdown:
        # Prefer system-stats
        warn, rid = get_stats()

        if warn is None or rid is None:
            # Fallback via manifest/report
            manifest = json_get("/api/qmdl-manifest")
            entry, rid2 = parse_newest_entry(manifest)
            if rid is None: rid = rid2
            w = count_warnings_from_manifest_entry(entry)
            if w is None and rid:
                w = count_warnings_from_report(json_get(f"/api/analysis-report/{rid}"))
            warn = warn if warn is not None else (w or 0)

        alert = (warn or 0) > 0
        if ALERT_ON_NEW and rid is not None and rid != last_id:
            alert = True

        if (rid != last_id) or (warn != last_warn) or (alert != last_alert):
            mqtt_publish(alert, rid, warn)
            last_id, last_warn, last_alert = rid, (warn or 0), alert

        now = time.time()
        if FORCE_ALERT_SECS > 0 and now >= next_forced:
            mqtt_publish(True, last_id, last_warn)
            last_alert = True
            next_forced = now + FORCE_ALERT_SECS
            if AUTOCLEAR_SECS > 0:
                clear_deadline = now + AUTOCLEAR_SECS

        if stdin_q is not None:
            try:
                while not stdin_q.empty():
                    _ = stdin_q.get_nowait()
                    mqtt_publish(True, last_id, last_warn)
                    last_alert = True
                    if AUTOCLEAR_SECS > 0:
                        clear_deadline = time.time() + AUTOCLEAR_SECS
            except Exception:
                pass

        if clear_deadline and time.time() >= clear_deadline:
            mqtt_publish(False, last_id, last_warn)
            last_alert = False
            clear_deadline = 0.0

        line = f"hb={'ok' if warn is not None else 'down'} last_id={last_id} warnings={last_warn} alert={'ON' if last_alert else 'OFF'}"
        if line != last_line:
            print(line, flush=True)
            last_line = line

        for _ in range(POLL):
            if _shutdown: break
            time.sleep(1)

    mqtt_teardown()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        try: mqtt_teardown()
        except Exception: pass
        raise
