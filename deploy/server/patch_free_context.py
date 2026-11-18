#!/usr/bin/env python3
"""Startup: load bulky main-context once through the free Light lane. Idempotent."""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path("/app/ouroboros/loop_llm_call.py")
MARKER = "OUROBOROS_FREE_CONTEXT"
ANCHOR = 'if (accumulated_usage.get(ROUND_STARTED_KEY) or {}).get("round_id") != round_id:'
# The anchor line already has its indent. The first line must not add another.
INSERT = """try:  # OUROBOROS_FREE_CONTEXT
                from ouroboros.free_context_load import apply_free_context_load
                send_messages = apply_free_context_load(
                    send_messages, llm=llm, accumulated_usage=accumulated_usage,
                    model=model, model_role=model_role, round_idx=round_idx,
                    task_id=task_id, task_type=task_type, drive_logs=drive_logs,
                )
            except Exception:
                pass
"""


def main() -> str:
    if not TARGET.is_file():
        return "loop_llm_call.py: missing"
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        return "loop_llm_call.py: present"
    if text.count(ANCHOR) != 1:
        return "loop_llm_call.py: snippet missing"
    indent = text.split(ANCHOR)[0].splitlines()[-1]
    if indent.strip() or not indent:
        return "loop_llm_call.py: anchor indent"
    text = text.replace(ANCHOR, INSERT + indent + ANCHOR, 1)
    compile(text, str(TARGET), "exec")
    TARGET.write_text(text, encoding="utf-8")
    return "loop_llm_call.py: applied"


if __name__ == "__main__":
    try:
        print("free context patch:", main())
    except Exception as exc:
        print(f"free context patch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
