#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/chromium-runtime}"
mkdir -p /data/chrome-profile /data/errors "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
rm -f /tmp/.X99-lock
rm -f /data/chrome-profile/SingletonLock /data/chrome-profile/SingletonSocket /data/chrome-profile/SingletonCookie

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY" -screen 0 "${XVFB_SCREEN:-1440x960x24}" -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
PIDS+=("$!")
sleep 1

fluxbox >/tmp/fluxbox.log 2>&1 &
PIDS+=("$!")

x11vnc -display "$DISPLAY" -forever -shared -nopw -localhost -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
PIDS+=("$!")

websockify --web=/usr/share/novnc/ 0.0.0.0:${NOVNC_PORT:-6080} localhost:5900 >/tmp/novnc.log 2>&1 &
PIDS+=("$!")

chromium   --user-data-dir=/data/chrome-profile   --remote-debugging-address=127.0.0.1   --remote-debugging-port=${BROWSER_CDP_PORT:-9222}   --no-sandbox   --disable-dev-shm-usage   --no-default-browser-check   --no-first-run   --lang=${BROWSER_LANGUAGE:-zh-HK,zh,en-US,en}   --window-size=${BROWSER_WINDOW_SIZE:-1158,848}   https://95598.cn/osgweb/login >/tmp/chromium.log 2>&1 &
PIDS+=("$!")
sleep 3

echo "SGCC noVNC ready on ${NOVNC_PORT:-6080}; persistent Chromium profile: /data/chrome-profile; CDP: 127.0.0.1:${BROWSER_CDP_PORT:-9222}" >&2
python3 -u /app/main.py &
PIDS+=("$!")

wait -n
exit $?
