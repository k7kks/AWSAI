#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_ROOT="${APP_ROOT:-/opt/kiro-relay}"
STATE_ROOT="${STATE_ROOT:-/var/lib/kiro-relay}"
CONFIG_ROOT="${CONFIG_ROOT:-/etc/kiro-relay}"
SERVICE_USER="${SERVICE_USER:-kirorelay}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/kkddytd/claude-api/releases/latest/download/claude-server-linux-amd64.tar.gz}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root."
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip curl tar rsync
else
  echo "This installer currently supports Debian/Ubuntu servers."
  exit 1
fi

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_ROOT/app" "$APP_ROOT/upstream" "$STATE_ROOT/upstream" "$STATE_ROOT/run" "$STATE_ROOT/snapshots" "$CONFIG_ROOT"

rsync -a --delete \
  --exclude '.venv' \
  --exclude 'dist' \
  --exclude 'run' \
  --exclude 'snapshots' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'portal.db' \
  --exclude 'relay.db' \
  --exclude 'upstream/data' \
  "$SOURCE_DIR/" "$APP_ROOT/app/"

tmp_archive="$(mktemp)"
curl -fsSL "$UPSTREAM_URL" -o "$tmp_archive"
rm -rf "$APP_ROOT/upstream"/*
tar -xzf "$tmp_archive" -C "$APP_ROOT/upstream"
rm -f "$tmp_archive"

upstream_bin="$(find "$APP_ROOT/upstream" -type f -name 'claude-server' | head -n 1)"
if [[ -z "$upstream_bin" ]]; then
  echo "Failed to locate claude-server after download."
  exit 1
fi

if [[ "$upstream_bin" != "$APP_ROOT/upstream/claude-server" ]]; then
  cp "$upstream_bin" "$APP_ROOT/upstream/claude-server"
fi
chmod +x "$APP_ROOT/upstream/claude-server"

python3 -m venv "$APP_ROOT/venv"
"$APP_ROOT/venv/bin/pip" install --upgrade pip
"$APP_ROOT/venv/bin/pip" install -r "$APP_ROOT/app/requirements.txt"

touch "$STATE_ROOT/portal.db"
rm -rf "$APP_ROOT/app/run" "$APP_ROOT/app/snapshots"
rm -f "$APP_ROOT/app/portal.db"
ln -sfn "$STATE_ROOT/run" "$APP_ROOT/app/run"
ln -sfn "$STATE_ROOT/snapshots" "$APP_ROOT/app/snapshots"
ln -sfn "$STATE_ROOT/portal.db" "$APP_ROOT/app/portal.db"

if [[ ! -f "$CONFIG_ROOT/relay.env" ]]; then
  install -m 0640 "$SCRIPT_DIR/relay.env.example" "$CONFIG_ROOT/relay.env"
fi

portal_service_tmp="$(mktemp)"
upstream_service_tmp="$(mktemp)"

sed \
  -e "s#__APP_ROOT__#$APP_ROOT#g" \
  -e "s#__STATE_ROOT__#$STATE_ROOT#g" \
  -e "s#__CONFIG_ROOT__#$CONFIG_ROOT#g" \
  -e "s#__SERVICE_USER__#$SERVICE_USER#g" \
  "$SCRIPT_DIR/kiro-portal.service" > "$portal_service_tmp"

sed \
  -e "s#__APP_ROOT__#$APP_ROOT#g" \
  -e "s#__STATE_ROOT__#$STATE_ROOT#g" \
  -e "s#__CONFIG_ROOT__#$CONFIG_ROOT#g" \
  -e "s#__SERVICE_USER__#$SERVICE_USER#g" \
  "$SCRIPT_DIR/kiro-upstream.service" > "$upstream_service_tmp"

install -m 0644 "$portal_service_tmp" /etc/systemd/system/kiro-portal.service
install -m 0644 "$upstream_service_tmp" /etc/systemd/system/kiro-upstream.service
rm -f "$portal_service_tmp" "$upstream_service_tmp"

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT" "$STATE_ROOT"

systemctl daemon-reload
systemctl enable --now kiro-upstream.service
systemctl enable --now kiro-portal.service

echo
echo "Relay services are installed."
echo "1. Edit $CONFIG_ROOT/relay.env"
echo "2. Bootstrap admin if needed:"
echo "   $APP_ROOT/venv/bin/python $APP_ROOT/app/server.py bootstrap-admin --email admin@example.com --password 'ChangeMe!2026' --name 'Relay Admin'"
echo "3. Put Caddy/Nginx in front of http://127.0.0.1:4173"
