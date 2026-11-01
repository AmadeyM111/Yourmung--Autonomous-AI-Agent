"""Durable registry of commitments and people follow-ups (stdlib only).

Storage: one JSON file, ``{"schema_version": 1, "items": [...]}``.  Writes are atomic
(temp file + ``os.replace``).  Concurrency model: a single writer process is assumed
(the skill's tool handlers); an in-process lock serialises threads.  Stored text is
data only and is never executed or interpreted.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import tempfile
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = 1
MAX_TITLE = 300
MAX_NOTES = 2000
MAX_SHORT = 200
MAX_BATCH = 30
STATUSES = ("open", "done", "snoozed", "cancelled")
_EDITABLE = ("title", "owner", "person", "due", "notes", "status")


def _clip(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _norm_date(value: Any, field: str = "due") -> str:
    """Accept ``YYYY-MM-DD`` or a full ISO datetime; return it normalised ('' allowed)."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if len(text) == 10:
            return _dt.date.fromisoformat(text).isoformat()
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD) or datetime, got {text[:40]!r}")


def _day(value: str) -> str:
    return value[:10]


class CommitmentStore:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self._lock = threading.Lock()

    # -- persistence -------------------------------------------------------------------
    def _load(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("items") if isinstance(data, dict) else None
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def _save(self, items: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".commitments.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"schema_version": SCHEMA_VERSION, "items": items}, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _build(title, owner, person, due, source, notes) -> Dict[str, Any]:
        title = _clip(title, MAX_TITLE)
        if not title:
            raise ValueError("title is required")
        return {
            "id": "c" + uuid.uuid4().hex[:8],
            "title": title,
            "owner": _clip(owner, MAX_SHORT),
            "person": _clip(person, MAX_SHORT),
            "due": _norm_date(due),
            "source": _clip(source, MAX_SHORT),
            "notes": _clip(notes, MAX_NOTES),
            "status": "open",
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        }

    # -- API ---------------------------------------------------------------------------
    def add(self, title, owner="", person="", due="", source="", notes="") -> Dict[str, Any]:
        record = self._build(title, owner, person, due, source, notes)
        with self._lock:
            items = self._load()
            items.append(record)
            self._save(items)
        return record

    def add_many(self, items: Iterable[Any]) -> Dict[str, Any]:
        batch = list(items or [])
        if len(batch) > MAX_BATCH:
            raise ValueError(f"at most {MAX_BATCH} commitments per call")
        records = []
        for index, raw in enumerate(batch):
            if not isinstance(raw, dict):
                raise ValueError(f"item {index} must be an object")
            try:
                records.append(self._build(raw.get("title"), raw.get("owner", ""), raw.get("person", ""),
                                           raw.get("due", ""), raw.get("source", ""), raw.get("notes", "")))
            except ValueError as exc:
                raise ValueError(f"item {index}: {exc}")
        with self._lock:
            existing = self._load()
            existing.extend(records)
            self._save(existing)
        return {"ids": [r["id"] for r in records], "count": len(records)}

    def get(self, cid: str) -> Optional[Dict[str, Any]]:
        return next((i for i in self._load() if i.get("id") == cid), None)

    def list(self, status="open", person="", due_before="", overdue_only=False, limit=50, today=None) -> List[Dict[str, Any]]:
        due_before = _norm_date(due_before, "due_before")
        today_s = _day(today) if today else _dt.date.today().isoformat()
        person_l = str(person or "").strip().lower()
        out = []
        for item in self._load():
            if status and status != "all" and item.get("status") != status:
                continue
            if person_l and person_l not in str(item.get("person", "")).lower():
                continue
            due = str(item.get("due") or "")
            if due_before and not (due and _day(due) <= _day(due_before)):
                continue
            if overdue_only and not (due and _day(due) < today_s and item.get("status") == "open"):
                continue
            out.append(item)
        out.sort(key=lambda i: (not i.get("due"), str(i.get("due") or ""), str(i.get("created_at"))))
        return out[:max(1, min(int(limit or 50), 200))]

    def update(self, cid: str, **fields) -> Dict[str, Any]:
        unknown = set(fields) - set(_EDITABLE)
        if unknown:
            raise ValueError("cannot update: " + ", ".join(sorted(unknown)))
        with self._lock:
            items = self._load()
            item = next((i for i in items if i.get("id") == cid), None)
            if item is None:
                raise ValueError(f"commitment {cid!r} not found")
            patch: Dict[str, Any] = {}
            for key, value in fields.items():
                if key == "title":
                    patch[key] = _clip(value, MAX_TITLE)
                    if not patch[key]:
                        raise ValueError("title cannot be empty")
                elif key == "notes":
                    patch[key] = _clip(value, MAX_NOTES)
                elif key == "due":
                    patch[key] = _norm_date(value)
                elif key == "status":
                    if value not in STATUSES:
                        raise ValueError("status must be one of " + ", ".join(STATUSES))
                    patch[key] = value
                else:
                    patch[key] = _clip(value, MAX_SHORT)
            item.update(patch)
            item["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            self._save(items)
            return dict(item)

    def done(self, cid: str, note: str = "") -> Dict[str, Any]:
        record = self.update(cid, status="done")
        if note:
            merged = (record.get("notes", "") + "\n" if record.get("notes") else "") + "done: " + str(note)
            record = self.update(cid, notes=merged[-MAX_NOTES:])
        return record

    def snooze(self, cid: str, until: str) -> Dict[str, Any]:
        if not str(until or "").strip():
            raise ValueError("until is required")
        return self.update(cid, due=until)

    def due_summary(self, now=None) -> Dict[str, List[Dict[str, Any]]]:
        now = now or _dt.datetime.now()
        today = now.date()
        horizon = today + _dt.timedelta(days=3)
        overdue, due_today, soon = [], [], []
        for item in self.list(status="open", limit=200):
            due = str(item.get("due") or "")
            if not due:
                continue
            day = _dt.date.fromisoformat(_day(due))
            if day < today:
                overdue.append(item)
            elif day == today:
                due_today.append(item)
            elif day <= horizon:
                soon.append(item)
        return {"overdue": overdue, "due_today": due_today, "due_next_3_days": soon}
