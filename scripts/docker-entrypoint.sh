#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:99
PROFILE_DIR="${SGCC_BROWSER_PROFILE:-/data/chrome-profile}"

mkdir -p "$PROFILE_DIR" /data/errors
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
