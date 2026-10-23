#!/bin/sh
# Start the virtual display and a window manager, signal readiness (/tmp/.sandbox-ready, only once the
# window manager owns the screen, so the first launched window is managed and focused), then live for at
# most MAX_LIFETIME seconds:
# the sleep is the container's main process, so the sandbox dies on schedule even if the MCP
# server that started it was killed and could not remove it.
set -eu
SCREEN="${SCREEN:-1280x800x24}"
MAX_LIFETIME="${MAX_LIFETIME:-1800}"

Xvfb :99 -screen 0 "$SCREEN" -nolisten tcp +extension RANDR >/tmp/xvfb.log 2>&1 &
i=0
until xdpyinfo -display :99 >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -gt 100 ] && { echo "Xvfb did not start" >&2; cat /tmp/xvfb.log >&2; exit 1; }
  sleep 0.1
done
openbox >/tmp/openbox.log 2>&1 &
i=0
until xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id'; do
  i=$((i + 1))
  [ "$i" -gt 100 ] && { echo "openbox did not start" >&2; cat /tmp/openbox.log >&2; exit 1; }
  sleep 0.1
done
touch /tmp/.sandbox-ready
exec sleep "$MAX_LIFETIME"
