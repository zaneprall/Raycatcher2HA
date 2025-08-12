# Multi-arch base with bashio + s6-overlay
ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.3.4
FROM ${BUILD_FROM}

# Packages: adb + python
RUN apk add --no-cache android-tools python3 py3-pip

# App files
COPY run.sh /run.sh
COPY requirements.txt /opt/rayhunter/requirements.txt
COPY rayhunter_bridge.py /opt/rayhunter/rayhunter_bridge.py

RUN chmod +x /run.sh && \
    python3 -m pip install --no-cache-dir -r /opt/rayhunter/requirements.txt

# s6-overlay expects /run.sh as entrypoint
