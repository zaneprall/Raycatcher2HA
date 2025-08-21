# Supervisor-compatible base with s6 + bashio
ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.3.4
FROM ${BUILD_FROM}

# OS deps
RUN apk add --no-cache android-tools python3 py3-pip usbutils

WORKDIR /opt/rayhunter

# Copy inputs
COPY requirements.txt .
COPY rayhunter_bridge.py .
COPY run.sh /run.sh

# Permissions
RUN chmod +x /run.sh

# PEP 668-safe: install Python deps into a venv
RUN python3 -m venv /opt/rayhunter/venv \
 && /opt/rayhunter/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/rayhunter/venv/bin/pip install --no-cache-dir -r /opt/rayhunter/requirements.txt

# Prefer venv
ENV PATH="/opt/rayhunter/venv/bin:${PATH}"

# s6-overlay will exec /run.sh
