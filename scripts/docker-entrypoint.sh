#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:99
PROFILE_DIR="${SGCC_BROWSER_PROFILE:-/data/chrome-profile}"
BROWSER_MODE="${SGCC_BROWSER_MODE:-local}"

mkdir -p /data/errors

case "$BROWSER_MODE" in
  cdp|cdp_attach|host_cdp|host-cdp|remote_debugging|remote-debugging|browser-service|browser_service|sidecar|container-google-cdp|container_google_cdp)
    # CDP modes attach to an external official Chrome instance. In
    # browser-service/sidecar mode the app asks the sidecar to launch Chrome on
    # demand; do not start Xvfb or touch Chrome profile locks in this container.
    exec python3 -u /app/main.py
    ;;
esac

mkdir -p "$PROFILE_DIR"
rm -f /tmp/.X99-lock
rm -f "$PROFILE_DIR"/SingletonLock "$PROFILE_DIR"/SingletonSocket "$PROFILE_DIR"/SingletonCookie

XVFB_PID=""
cleanup() {
  if [ -n "${XVFB_PID:-}" ]; then
    kill "$XVFB_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

Xvfb :99 -screen 0 1440x960x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
XVFB_PID="$!"
sleep 1
if ! kill -0 "$XVFB_PID" >/dev/null 2>&1; then
  cat /tmp/xvfb.log >&2 || true
  exit 1
fi

exec python3 -u /app/main.py
