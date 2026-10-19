"""Exact model allowlist via Claude Code managed settings (`bin/stack managed-settings`).

``availableModelsMatch`` (and ``deniedModels``) are honoured only from managed settings; in user, project and
local settings or ``--settings`` Claude Code ignores them with a warning, and ``availableModels`` there matches
by prefix (a listed id also admits later ids that extend it). Exact enforcement therefore needs the OS-level
managed-settings file, which only an administrator can write.
"""
from __future__ import annotations

import json
import os
import platform
from typing import Optional

from . import tiers

MANAGED_ONLY_KEYS = ("availableModelsMatch", "deniedModels")


def managed_path() -> str:
    system = platform.system()
    if system == "Darwin":
        return "/Library/Application Support/ClaudeCode/managed-settings.json"
    if system == "Windows":
        return r"C:\Program Files\ClaudeCode\managed-settings.json"
    return "/etc/claude-code/managed-settings.json"  # Linux and WSL


def allowlist() -> dict:
    return {"availableModels": sorted(tiers.allowed_models()), "availableModelsMatch": "exact",
            "enforceAvailableModels": True}


def merged(path: Optional[str] = None) -> dict:
    """The managed file's current content with the allowlist keys set (other keys kept)."""
    cur: dict = {}
    try:
        with open(path or managed_path(), encoding="utf-8") as fh:
            cur = json.load(fh)
    except (OSError, ValueError):
        pass
    return {**cur, **allowlist()}


def install(path: Optional[str] = None) -> bool:
    """Write the merged file; False when the location is not writable (needs an administrator)."""
    p = path or managed_path()
    data = json.dumps(merged(p), indent=2) + "\n"
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, p)
        return True
    except OSError:
        return False
