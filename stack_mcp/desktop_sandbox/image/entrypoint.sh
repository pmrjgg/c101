#!/bin/sh
# Start the virtual display and a window manager, then live for at most MAX_LIFETIME seconds:
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
exec sleep "$MAX_LIFETIME"
