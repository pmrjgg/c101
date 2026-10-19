#!/usr/bin/env bash
# Install / update the agent stack. Requires uv (https://docs.astral.sh/uv/);
# everything Python runs on CPython 3.13 managed by uv.
#
#   ./install.sh                 project scope: uv env, ~/.claude/stack link, ~/.claude/stack.env template
#   ./install.sh --user          + agents/skills/workflows/MCP servers/hooks in every project
#   ./install.sh --main-agent    + make `delegator` the main-thread agent for all sessions
#   ./install.sh --dry-run ...   show what would change
set -euo pipefail
REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'MSG'
uv is required but was not found. Install it with one of:
  brew install uv
  curl -LsSf https://astral.sh/uv/install.sh | sh
then re-run ./install.sh
MSG
  exit 1
fi

dry=0
for a in "$@"; do [[ "$a" == "--dry-run" ]] && dry=1; done

echo "uv $(uv --version | awk '{print $2}')"
if [[ $dry -eq 0 ]]; then
  uv python install 3.13
  if [[ -f "$REPO/uv.lock" ]]; then
    uv sync --project "$REPO" --python 3.13 --locked
  else
    uv sync --project "$REPO" --python 3.13
  fi
else
  echo "[dry-run] uv python install 3.13 && uv sync --project $REPO --python 3.13"
fi

command -v node >/dev/null 2>&1 || echo "note: node/npx not found — the Playwright MCP server (npx @playwright/mcp) needs Node 18+." >&2

exec uv run --quiet --project "$REPO" --python 3.13 python -m stack.install "$@"
