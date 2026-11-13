#!/usr/bin/env python3
"""Container startup hook: let OUROBOROS_DISABLED_TOOLS (comma-separated names) withhold tools globally.

Each exposed tool schema costs input tokens on every model call. The upstream registry only supports a
per-task `disabled_tools` contract, so this adds a global list from the environment. Idempotent; never raises.
"""
import pathlib
import sys

MARKER = "OUROBOROS_DISABLED_TOOLS_PATCH"
TARGET = pathlib.Path("/app/ouroboros/tools/registry_guards.py")
OLD = "    names: set = set()\n    for source in (metadata, contract):\n        raw = source.get(\"disabled_tools\")"
NEW = ("    names: set = set()\n"
       "    import os as _os  # OUROBOROS_DISABLED_TOOLS_PATCH\n"
       "    names.update(n.strip() for n in str(_os.environ.get(\"OUROBOROS_DISABLED_TOOLS\") or \"\").split(\",\") if n.strip())\n"
       "    for source in (metadata, contract):\n        raw = source.get(\"disabled_tools\")")

try:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("tools patch: present")
    elif text.count(OLD) != 1:
        print("tools patch skipped: expected snippet not found", file=sys.stderr)
    else:
        text = text.replace(OLD, NEW, 1)
        compile(text, str(TARGET), "exec")
        TARGET.write_text(text, encoding="utf-8")
        print("tools patch: applied")
except Exception as exc:
    print(f"tools patch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
