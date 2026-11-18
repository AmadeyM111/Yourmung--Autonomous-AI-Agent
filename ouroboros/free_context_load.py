"""Load bulky task context through the free Light lane once per task.

If that lane is unavailable, the same brief is loaded once on the main model.
If both fail, the original messages stay and the reply still runs on main.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

BRIEF_KEY = "_free_context_brief"
LANE_KEY = "_free_context_lane"
MARKER = "OUROBOROS_FREE_CONTEXT_BRIEF"
_KEEP_CHARS = 4000
_MIN_SOURCE_CHARS = 4000
_CHUNK_CHARS = 60_000
_CALL_TIMEOUT_SEC = 35.0
_MAX_BRIEF_TOKENS = 1200
_OUTAGE_MARKERS = (
    "unavailable", "overloaded", "rate limit", "too many requests", "try again",
    "timeout", "timed out", "bad gateway", "service unavailable",
    "недоступ", "перегруз", "лимит запросов",
)

Loader = Callable[[str], str]


def apply_free_context_load(
    messages: List[Dict[str, Any]],
    *,
    llm: Any,
    accumulated_usage: Dict[str, Any],
    model: str,
    model_role: str,
    round_idx: int,
    task_id: str,
    task_type: str,
    drive_logs: Optional[pathlib.Path],
    loader: Optional[Loader] = None,
    fallback_loader: Optional[Loader] = None,
) -> List[Dict[str, Any]]:
    """Swap a long system view for a stored brief, loading it once."""
    if str(model_role or "main") != "main":
        return messages
    if ":free" in str(model or ""):
        return messages
    if not messages:
        return messages
    system_at = next((i for i, row in enumerate(messages) if row.get("role") == "system"), None)
    if system_at is None:
        return messages
    content = messages[system_at].get("content")
    if _has_marker(content):
        return messages
    keep, source = _split_keep_and_source(content)
    if len(source) < _MIN_SOURCE_CHARS:
        return messages
    brief = accumulated_usage.get(BRIEF_KEY)
    lane = str(accumulated_usage.get(LANE_KEY) or "")
    if not isinstance(brief, str):
        brief, lane = _load_once(
            source, llm=llm, loader=loader, fallback_loader=fallback_loader, model=model,
            task_id=task_id, task_type=task_type, round_idx=round_idx, drive_logs=drive_logs,
        )
        accumulated_usage[BRIEF_KEY] = brief
        accumulated_usage[LANE_KEY] = lane
    if not brief:
        return messages
    swapped = list(messages)
    swapped[system_at] = _with_brief(keep, brief, lane or "free")
    return swapped


def _load_once(
    source: str, *, llm: Any, loader: Optional[Loader], fallback_loader: Optional[Loader],
    model: str, task_id: str, task_type: str, round_idx: int, drive_logs: Optional[pathlib.Path],
) -> Tuple[str, str]:
    light_model = ""
    free_reason = ""
    try:
        if loader is not None:
            text = loader(source)
            light_model = "test"
        else:
            text, light_model = _load_with_light(llm, source)
        brief = str(text or "").strip()
        if _usable(brief, source):
            _emit(drive_logs, task_id, task_type, round_idx, ok=True, model=light_model,
                  lane="free", fallback=False, in_chars=len(source), out_chars=len(brief), reason="")
            return brief, "free"
        free_reason = "unusable" if brief else "empty"
    except RuntimeError as exc:
        if str(exc) == "light_not_free":
            _emit(drive_logs, task_id, task_type, round_idx, ok=False, model=light_model,
                  lane="", fallback=False, in_chars=len(source), out_chars=0, reason="light_not_free")
            return "", ""
        free_reason = type(exc).__name__
        log.warning("Free context load failed; switching to the main model", exc_info=True)
    except Exception as exc:
        free_reason = type(exc).__name__
        log.warning("Free context load failed; switching to the main model", exc_info=True)

    try:
        if fallback_loader is not None:
            brief = str(fallback_loader(source) or "").strip()
            used = model or "main"
        elif loader is None and llm is not None:
            brief, used = _load_with_main(llm, source, model)
            brief = str(brief or "").strip()
        else:
            _emit(drive_logs, task_id, task_type, round_idx, ok=False, model=light_model,
                  lane="", fallback=False, in_chars=len(source), out_chars=0, reason=free_reason)
            return "", ""
        if _usable(brief, source):
            _emit(drive_logs, task_id, task_type, round_idx, ok=True, model=used,
                  lane="main", fallback=True, in_chars=len(source), out_chars=len(brief), reason=free_reason)
            return brief, "main"
        free_reason = f"{free_reason}:main_unusable" if free_reason else "main_unusable"
    except Exception as exc:
        free_reason = f"{free_reason}:{type(exc).__name__}" if free_reason else type(exc).__name__
        log.warning("Main context fallback failed; keeping the original system view", exc_info=True)
    _emit(drive_logs, task_id, task_type, round_idx, ok=False, model=model,
          lane="", fallback=True, in_chars=len(source), out_chars=0, reason=free_reason)
    return "", ""


def _load_with_light(llm: Any, source: str) -> tuple:
    from ouroboros.consolidator import _light_dispatch_binding

    binding = _light_dispatch_binding()
    light_model = str(binding.get("model") or "")
    if ":free" not in light_model and not binding.get("use_local"):
        raise RuntimeError("light_not_free")
    binding = {**binding, "model_role": "light"}
    chunks = _chunks(source)
    parts = [_ask(llm, binding, _shrink_prompt(chunk, len(chunks), index)) for index, chunk in enumerate(chunks, 1)]
    if len(parts) == 1:
        return parts[0], light_model
    return _ask(llm, binding, _merge_prompt(parts)), light_model


def _load_with_main(llm: Any, source: str, model: str) -> tuple:
    if llm is None or not str(model or "").strip() or ":free" in str(model):
        raise RuntimeError("no_main")
    binding = {"model": model, "use_local": False, "model_account_override": None, "model_role": "main"}
    return _ask(llm, binding, _shrink_prompt(_fallback_source(source), 1, 1)), model


def _ask(llm: Any, binding: Dict[str, Any], prompt: str) -> str:
    message, _usage = llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model=binding["model"],
        use_local=bool(binding.get("use_local")),
        model_role=str(binding.get("model_role") or "light"),
        model_account_override=binding.get("model_account_override"),
        reasoning_effort="low",
        max_tokens=_MAX_BRIEF_TOKENS,
        tools=None,
        tool_choice="none",
        timeout=_CALL_TIMEOUT_SEC,
        wait_for_resources=False,
    )
    return _message_text(message)


def _usable(brief: str, source: str) -> bool:
    if len(brief) < 40 or len(brief) > max(int(len(source) * 0.8), 8000):
        return False
    if len(brief) < 500 and _looks_like_outage(brief):
        return False
    return True


def _looks_like_outage(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _OUTAGE_MARKERS)


def _shrink_prompt(chunk: str, parts: int, index: int) -> str:
    where = f" Часть {index} из {parts}." if parts > 1 else ""
    return (
        "Сожми рабочий контекст агента в бриф на русском."
        f"{where} Только факты из текста. Не выдумывай. "
        "Сохрани имена, id, запреты, бюджеты, пути и решения хозяина. "
        "Не копируй книги целиком. До 900 слов.\n\n"
        + chunk
    )


def _merge_prompt(parts: List[str]) -> str:
    body = "\n\n".join(f"--- часть {i} ---\n{part}" for i, part in enumerate(parts, 1))
    return (
        "Слей части брифа в один рабочий контекст на русском. "
        "Только факты из частей. Не выдумывай. Сохрани имена, id, запреты, бюджеты. "
        "До 900 слов.\n\n" + body
    )


def _chunks(source: str) -> List[str]:
    if len(source) <= _CHUNK_CHARS:
        return [source]
    if len(source) <= _CHUNK_CHARS * 2:
        return [source[:_CHUNK_CHARS], source[_CHUNK_CHARS:]]
    return [source[:_CHUNK_CHARS], "Середина исходного контекста опущена.\n\n" + source[-_CHUNK_CHARS:]]


def _fallback_source(source: str) -> str:
    if len(source) <= _CHUNK_CHARS:
        return source
    half = _CHUNK_CHARS // 2
    return source[:half] + "\n\nСередина исходного контекста опущена.\n\n" + source[-half:]


def _split_keep_and_source(content: Any) -> tuple:
    blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
    keep: List[Any] = []
    source: List[str] = []
    for block in blocks:
        text = _block_text(block)
        if text and len(text) > _KEEP_CHARS:
            source.append(text)
        else:
            keep.append(block)
    return keep, "\n\n".join(source)


def _with_brief(keep: List[Any], brief: str, lane: str) -> Dict[str, Any]:
    if lane == "main":
        lead = "Бесплатная модель была недоступна. Бриф собрала основная модель."
    else:
        lead = "Длинные книги и память этого хода заменены брифом бесплатной модели."
    note = {"type": "text", "text": f"{MARKER}\n{lead} Если факта нет в брифе и в коротких блоках выше, не выдумывай.\n\n{brief}"}
    return {"role": "system", "content": [*keep, note] if keep else [note]}


def _has_marker(content: Any) -> bool:
    if isinstance(content, str):
        return MARKER in content
    if isinstance(content, list):
        return any(MARKER in _block_text(block) for block in content)
    return False


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return ""


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(_block_text(block) for block in content).strip()
    return ""


def _emit(
    drive_logs: Optional[pathlib.Path], task_id: str, task_type: str, round_idx: int, *,
    ok: bool, model: str, lane: str, fallback: bool, in_chars: int, out_chars: int, reason: str,
) -> None:
    if drive_logs is None:
        return
    try:
        from ouroboros.utils import append_jsonl, utc_now_iso

        append_jsonl(pathlib.Path(drive_logs) / "events.jsonl", {
            "ts": utc_now_iso(),
            "type": "free_context_load",
            "task_id": task_id,
            "task_type": task_type,
            "round": round_idx,
            "ok": ok,
            "model": model,
            "lane": lane,
            "fallback": fallback,
            "in_chars": in_chars,
            "out_chars": out_chars,
            "reason": reason,
        })
    except Exception:
        log.debug("Failed to emit free context load event", exc_info=True)
