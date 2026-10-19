"""Imported first by every test module: drop environment variables that would leak the caller's stack or
Claude Code session settings into the tests. Hooks run as subprocesses and inherit os.environ, so a value set
in a developer shell or a cloud container (e.g. CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1) would change what
they decide. Tests that need one of these set it explicitly."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIXES = ("CLAUDE_STACK_",)
NAMES = {
    "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_PROJECT_DIR", "CLAUDE_PROJECTS_ROOT", "STACK_MAIN_AGENT",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ENABLE_TOOL_SEARCH",
}
try:  # tier variables (ADVANCED_MODEL, ...) override config/models.json
    with open(os.path.join(ROOT, "config", "models.json"), encoding="utf-8") as fh:
        NAMES |= set(json.load(fh).get("tiers", {}))
except (OSError, ValueError):
    NAMES |= {"ADVANCED_MODEL", "MEDIUM_MODEL", "LOW_MODEL"}

SCRUBBED = sorted(k for k in os.environ if k in NAMES or k.startswith(PREFIXES))
for _k in SCRUBBED:
    del os.environ[_k]
