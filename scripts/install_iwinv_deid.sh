#!/usr/bin/env bash
# Run as root after uploading only the worker and detector under /opt/remind-deid.
set -euo pipefail
id remind-deid >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin remind-deid
install -d -m 750 -o root -g remind-deid /etc/remind-deid
if [ ! -f /etc/remind-deid/worker.env ]; then
  umask 077
  python3 - <<'PY'
import secrets
from pathlib import Path
Path('/etc/remind-deid/worker.env').write_text('DEID_SERVICE_TOKEN=' + secrets.token_urlsafe(48) + '\n')
PY
fi
if [ ! -f /etc/remind-deid/server.crt ]; then
  openssl req -x509 -newkey rsa:3072 -nodes -days 365 \
    -keyout /etc/remind-deid/server.key -out /etc/remind-deid/server.crt \
    -subj '/CN=ReMind iwinv deidentification' \
    -addext 'subjectAltName=IP:49.247.174.195,IP:127.0.0.1' >/dev/null 2>&1
fi
chown root:remind-deid /etc/remind-deid/server.key /etc/remind-deid/server.crt
chmod 640 /etc/remind-deid/server.key /etc/remind-deid/server.crt
umask 022
python3 -m venv /opt/remind-deid/venv
/opt/remind-deid/venv/bin/pip install --disable-pip-version-check 'fastapi==0.128.8' 'uvicorn==0.40.0' 'pydantic==2.12.5'
chown -R root:remind-deid /opt/remind-deid
chmod -R g+rX,o-rwx /opt/remind-deid
cat > /etc/systemd/system/remind-deid.service <<'UNIT'
[Unit]
Description=ReMind private entity discovery API
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=remind-deid
Group=remind-deid
WorkingDirectory=/opt/remind-deid
EnvironmentFile=/etc/remind-deid/worker.env
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/remind-deid/venv/bin/uvicorn app.deid_worker:app --host 0.0.0.0 --port 443 --workers 1 --no-access-log --limit-concurrency 8 --timeout-keep-alive 5 --ssl-keyfile /etc/remind-deid/server.key --ssl-certfile /etc/remind-deid/server.crt
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryMax=768M

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now remind-deid
systemctl is-active remind-deid
