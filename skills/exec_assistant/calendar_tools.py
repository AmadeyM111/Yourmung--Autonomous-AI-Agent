"""Read-only Google Calendar tools for the executive-assistant skill.

Pure functions: each takes a ``GoogleClient`` and returns a JSON-serialisable dict wrapped
with ``untrusted`` (event titles and descriptions are third-party text).  Nothing here
writes to the calendar.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # loaded as part of a package
    from .google_client import CALENDAR_API, GoogleClient, untrusted
except ImportError:  # loaded with skills/exec_assistant on sys.path
    from google_client import CALENDAR_API, GoogleClient, untrusted  # type: ignore

MAX_AGENDA_DAYS = 14
MAX_FREE_DAYS = 31
TITLE_MAX = 200
EXCERPT_MAX = 800
DETAIL_DESC_MAX = 2000
BACK_TO_BACK_GAP_MIN = 5
HEAVY_DAY_MINUTES = 6 * 60
MAX_ATTENDEES_LISTED = 10
_PRIMARY = f"{CALENDAR_API}/calendars/primary/events"


# -- helpers -----------------------------------------------------------------------------
def _zone(tz: str) -> ZoneInfo:
    name = (tz or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"Unknown time zone '{name}'. Use an IANA name such as Europe/Moscow or UTC.") from None


def _clip(text: Any, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _clamp_int(value: Any, low: int, high: int, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number.") from None
    return max(low, min(high, number))


def _now(now: Optional[dt.datetime], zone: ZoneInfo) -> dt.datetime:
    if now is None:
        return dt.datetime.now(zone)
    return now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)


def _day_start(moment: dt.datetime, zone: ZoneInfo) -> dt.datetime:
    return dt.datetime.combine(moment.date(), dt.time(0, 0), tzinfo=zone)


def _parse_start(start: str, zone: ZoneInfo, now: dt.datetime) -> dt.datetime:
    start = (start or "").strip()
    if not start:
        return _day_start(now, zone)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            return dt.datetime.combine(dt.date.fromisoformat(start), dt.time(0, 0), tzinfo=zone)
        parsed = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Cannot read start '{start}'. Use YYYY-MM-DD or an ISO 8601 date-time.") from None
    return parsed.astimezone(zone) if parsed.tzinfo else parsed.replace(tzinfo=zone)


def _event_time(node: Any, zone: ZoneInfo) -> Tuple[Optional[dt.datetime], bool]:
    """Return (aware datetime in zone, all_day)."""
    node = node if isinstance(node, dict) else {}
    if node.get("dateTime"):
        parsed = dt.datetime.fromisoformat(str(node["dateTime"]).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(zone), False
    if node.get("date"):
        day = dt.date.fromisoformat(str(node["date"]))
        return dt.datetime.combine(day, dt.time(0, 0), tzinfo=zone), True
    return None, False


def _list_events(client: GoogleClient, time_min: dt.datetime, time_max: dt.datetime, zone: ZoneInfo) -> List[dict]:
    items: List[dict] = []
    token = ""
    for _ in range(5):
        page = client.get(
            _PRIMARY, singleEvents="true", orderBy="startTime", maxResults=250,
            timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
            timeZone=zone.key, pageToken=token,
        )
        items.extend(e for e in page.get("items") or [] if isinstance(e, dict))
        token = str(page.get("nextPageToken") or "")
        if not token:
            break
    return [e for e in items if e.get("status") != "cancelled"]


def _own_status(event: dict) -> str:
    for person in event.get("attendees") or []:
        if isinstance(person, dict) and person.get("self"):
            return str(person.get("responseStatus") or "")
    return ""


def _meeting_link(event: dict) -> str:
    if event.get("hangoutLink"):
        return str(event["hangoutLink"])
    for entry in (event.get("conferenceData") or {}).get("entryPoints") or []:
        if isinstance(entry, dict) and entry.get("entryPointType") == "video" and entry.get("uri"):
            return str(entry["uri"])
    return ""


def _organizer(event: dict) -> str:
    org = event.get("organizer") or {}
    return str(org.get("email") or org.get("displayName") or "")


def _summarise(event: dict, zone: ZoneInfo, *, desc_max: int = EXCERPT_MAX) -> Dict[str, Any]:
    start, all_day = _event_time(event.get("start"), zone)
    end, _ = _event_time(event.get("end"), zone)
    attendees = [a for a in event.get("attendees") or [] if isinstance(a, dict)]
    return {
        "id": str(event.get("id") or ""),
        "title": _clip(event.get("summary") or "(no title)", TITLE_MAX),
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "all_day": all_day,
        "location": _clip(event.get("location"), TITLE_MAX),
        "attendees_count": len(attendees),
        "attendees": [str(a.get("email")) for a in attendees if a.get("email")][:MAX_ATTENDEES_LISTED],
        "organizer": _organizer(event),
        "response_status": _own_status(event),
        "meeting_link": _meeting_link(event),
        "description_excerpt": _clip(event.get("description"), desc_max),
    }


def _timed_busy_events(client: GoogleClient, time_min, time_max, zone) -> List[Dict[str, Any]]:
    """Timed events that really occupy the owner: not declined, not 'free'."""
    out = []
    for event in _list_events(client, time_min, time_max, zone):
        start, all_day = _event_time(event.get("start"), zone)
        end, _ = _event_time(event.get("end"), zone)
        if all_day or start is None or end is None or end <= start:
            continue
        if event.get("transparency") == "transparent" or _own_status(event) == "declined":
            continue
        out.append({"title": _clip(event.get("summary") or "(no title)", TITLE_MAX),
                    "id": str(event.get("id") or ""), "_s": start, "_e": end})
    out.sort(key=lambda e: (e["_s"], e["_e"]))
    return out


def _brief(e: Dict[str, Any]) -> Dict[str, str]:
    return {"id": e["id"], "title": e["title"], "start": e["_s"].isoformat(), "end": e["_e"].isoformat()}


def _minutes(delta: dt.timedelta) -> int:
    return int(round(delta.total_seconds() / 60))


# -- tools -------------------------------------------------------------------------------
def agenda(client: GoogleClient, days: int = 1, start: str = "", tz: str = "UTC",
           now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    zone = _zone(tz)
    days = _clamp_int(days, 1, MAX_AGENDA_DAYS, "days")
    begin = _parse_start(start, zone, _now(now, zone))
    finish = begin + dt.timedelta(days=days)
    events = [_summarise(e, zone) for e in _list_events(client, begin, finish, zone)]
    return untrusted({
        "ok": True,
        "range": {"start": begin.isoformat(), "end": finish.isoformat(), "days": days, "tz": zone.key},
        "events": events,
    })


def conflicts(client: GoogleClient, days: int = 7, tz: str = "UTC",
              now: Optional[dt.datetime] = None, start: str = "") -> Dict[str, Any]:
    zone = _zone(tz)
    days = _clamp_int(days, 1, 31, "days")
    begin = _parse_start(start, zone, _now(now, zone))
    finish = begin + dt.timedelta(days=days)
    evs = _timed_busy_events(client, begin, finish, zone)

    overlaps = []
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            if b["_s"] >= a["_e"]:
                break  # sorted by start, nothing later can overlap a
            overlap = min(a["_e"], b["_e"]) - b["_s"]
            overlaps.append({"a": _brief(a), "b": _brief(b), "overlap_minutes": _minutes(overlap)})

    chains: List[List[Dict[str, Any]]] = []
    current = evs[:1]
    for prev, nxt in zip(evs, evs[1:]):
        gap = _minutes(nxt["_s"] - prev["_e"])
        if 0 <= gap < BACK_TO_BACK_GAP_MIN:
            current.append(nxt)
        else:
            if len(current) >= 3:
                chains.append(current)
            current = [nxt]
    if len(current) >= 3:
        chains.append(current)

    per_day: Dict[str, List[Tuple[dt.datetime, dt.datetime]]] = {}
    for e in evs:
        per_day.setdefault(e["_s"].date().isoformat(), []).append((e["_s"], e["_e"]))
    heavy = []
    for day, spans in sorted(per_day.items()):
        total = dt.timedelta()
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                total += cur_e - cur_s
                cur_s, cur_e = s, e
        total += cur_e - cur_s
        if _minutes(total) > HEAVY_DAY_MINUTES:
            heavy.append({"date": day, "meeting_minutes": _minutes(total)})

    return untrusted({
        "ok": True,
        "range": {"start": begin.isoformat(), "end": finish.isoformat(), "days": days, "tz": zone.key},
        "overlaps": overlaps,
        "back_to_back_chains": [
            {"count": len(c), "events": [_brief(e) for e in c]} for c in chains],
        "heavy_days": heavy,
    })


def _hhmm(value: str, name: str) -> dt.time:
    try:
        hour, minute = (int(p) for p in str(value).strip().split(":"))
        return dt.time(hour, minute)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must look like HH:MM, e.g. 09:00.") from None


def free_slots(client: GoogleClient, duration_min: int = 30, days: int = 5, work_start: str = "09:00",
               work_end: str = "18:00", tz: str = "UTC", skip_weekends: bool = True,
               now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    zone = _zone(tz)
    duration_min = _clamp_int(duration_min, 1, 24 * 60, "duration_min")
    days = _clamp_int(days, 1, MAX_FREE_DAYS, "days")
    w_start, w_end = _hhmm(work_start, "work_start"), _hhmm(work_end, "work_end")
    if w_end <= w_start:
        raise ValueError("work_end must be later than work_start.")
    current = _now(now, zone)
    first = _day_start(current, zone)
    last = first + dt.timedelta(days=days)

    data = client.post(f"{CALENDAR_API}/freeBusy", {
        "timeMin": first.isoformat(), "timeMax": last.isoformat(),
        "timeZone": zone.key, "items": [{"id": "primary"}],
    })
    busy_raw = ((data.get("calendars") or {}).get("primary") or {}).get("busy") or []
    busy: List[Tuple[dt.datetime, dt.datetime]] = []
    for item in busy_raw:
        s, _ = _event_time({"dateTime": item.get("start")}, zone)
        e, _ = _event_time({"dateTime": item.get("end")}, zone)
        if s and e and e > s:
            busy.append((s, e))
    busy.sort()

    need = dt.timedelta(minutes=duration_min)
    out_days = []
    for offset in range(days):
        day = first.date() + dt.timedelta(days=offset)
        if skip_weekends and day.weekday() >= 5:
            continue
        win_s = dt.datetime.combine(day, w_start, tzinfo=zone)
        win_e = dt.datetime.combine(day, w_end, tzinfo=zone)
        cursor = max(win_s, current) if day == current.date() else win_s
        windows = []
        for b_s, b_e in busy:
            if b_e <= cursor or b_s >= win_e:
                continue
            if b_s > cursor and b_s - cursor >= need:
                windows.append((cursor, b_s))
            cursor = max(cursor, b_e)
        if win_e - cursor >= need:
            windows.append((cursor, win_e))
        out_days.append({
            "date": day.isoformat(),
            "windows": [{"start": s.isoformat(), "end": e.isoformat(), "minutes": _minutes(e - s)}
                        for s, e in windows],
        })
    return untrusted({
        "ok": True,
        "duration_min": duration_min,
        "working_hours": {"start": w_start.strftime("%H:%M"), "end": w_end.strftime("%H:%M"), "tz": zone.key},
        "days": out_days,
    })


def event_detail(client: GoogleClient, event_id: str, tz: str = "UTC") -> Dict[str, Any]:
    event_id = str(event_id or "").strip()
    if not event_id:
        raise ValueError("event_id is required.")
    zone = _zone(tz)
    event = client.get(f"{_PRIMARY}/{urllib.parse.quote(event_id, safe='')}", timeZone=zone.key)
    detail = _summarise(event, zone, desc_max=DETAIL_DESC_MAX)
    detail["description"] = detail.pop("description_excerpt")
    detail["status"] = str(event.get("status") or "")
    detail["attendees"] = [
        {"email": str(a.get("email") or ""), "name": _clip(a.get("displayName"), TITLE_MAX),
         "response_status": str(a.get("responseStatus") or ""), "organizer": bool(a.get("organizer")),
         "self": bool(a.get("self")), "optional": bool(a.get("optional"))}
        for a in event.get("attendees") or [] if isinstance(a, dict)
    ]
    detail["html_link"] = str(event.get("htmlLink") or "")
    return untrusted({"ok": True, "event": detail})
