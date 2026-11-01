import datetime as dt
import importlib.util
import json
import pathlib
import sys
import urllib.parse
from zoneinfo import ZoneInfo

import pytest

SKILL = pathlib.Path(__file__).resolve().parents[1] / "skills" / "exec_assistant"
sys.path.insert(0, str(SKILL))

import calendar_tools as ct  # noqa: E402
import google_client as gc  # noqa: E402

TZ = "Europe/Moscow"
Z = ZoneInfo(TZ)
SETTINGS = {k: "x" for k in gc.SETTING_KEYS}


class Fake:
    def __init__(self, events=None, busy=None, single=None):
        self.events, self.busy, self.single = events or [], busy or [], single
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, body))
        if url == gc.TOKEN_URL:
            return 200, json.dumps({"access_token": "t", "expires_in": 3600}).encode()
        if url.startswith(gc.CALENDAR_API + "/freeBusy"):
            return 200, json.dumps({"calendars": {"primary": {"busy": self.busy}}}).encode()
        if "/events/" in url.split("?")[0]:
            return 200, json.dumps(self.single or {}).encode()
        return 200, json.dumps({"items": self.events}).encode()


def client(fake):
    return gc.GoogleClient(lambda: SETTINGS, transport=fake)


def ev(i, start, end, **kw):
    d = {"id": i, "summary": f"Event {i}", "start": {"dateTime": start}, "end": {"dateTime": end}}
    d.update(kw)
    return d


NOW = dt.datetime(2026, 11, 2, 8, 0, tzinfo=Z)  # Monday


def test_agenda_timed_allday_cancelled():
    fake = Fake([
        ev("1", "2026-11-02T10:00:00+03:00", "2026-11-02T11:00:00+03:00",
           description="d" * 2000, hangoutLink="https://meet/x", organizer={"email": "o@x.com"},
           attendees=[{"email": f"a{n}@x.com"} for n in range(12)] + [{"email": "me@x.com", "self": True, "responseStatus": "accepted"}]),
        {"id": "2", "summary": "Holiday", "start": {"date": "2026-11-02"}, "end": {"date": "2026-11-03"}},
        ev("3", "2026-11-02T12:00:00+03:00", "2026-11-02T13:00:00+03:00", status="cancelled"),
    ])
    out = ct.agenda(client(fake), days=30, tz=TZ, now=NOW)
    assert out["warning"] == gc.UNTRUSTED_NOTE
    assert out["range"]["days"] == 14
    assert out["range"]["start"] == "2026-11-02T00:00:00+03:00"
    assert [e["id"] for e in out["events"]] == ["1", "2"]
    e1, e2 = out["events"]
    assert len(e1["description_excerpt"]) <= 800
    assert len(e1["attendees"]) == 10 and e1["attendees_count"] == 13
    assert e1["response_status"] == "accepted" and e1["meeting_link"] == "https://meet/x"
    assert e1["organizer"] == "o@x.com" and e1["start"] == "2026-11-02T10:00:00+03:00"
    assert e2["all_day"] is True and e2["start"] == "2026-11-02T00:00:00+03:00"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(fake.calls[-1][1]).query)
    assert query["singleEvents"] == ["true"] and query["orderBy"] == ["startTime"]
    json.dumps(out)


def test_agenda_explicit_start_and_tz_offset():
    fake = Fake([ev("1", "2026-11-02T07:00:00Z", "2026-11-02T08:00:00Z")])
    out = ct.agenda(client(fake), start="2026-12-01", tz="America/New_York")
    assert out["range"]["start"] == "2026-12-01T00:00:00-05:00"
    out = ct.agenda(client(fake), tz=TZ, now=NOW)
    assert out["events"][0]["start"] == "2026-11-02T10:00:00+03:00"


def test_unknown_tz_rejected():
    with pytest.raises(ValueError, match="Unknown time zone"):
        ct.agenda(client(Fake()), tz="Mars/Base")
    with pytest.raises(ValueError):
        ct.free_slots(client(Fake()), tz="Nope")


def test_conflicts_overlap_backtoback_declined():
    fake = Fake([
        ev("a", "2026-11-02T10:00:00+03:00", "2026-11-02T11:00:00+03:00"),
        ev("b", "2026-11-02T10:30:00+03:00", "2026-11-02T11:30:00+03:00"),
        ev("d", "2026-11-02T10:00:00+03:00", "2026-11-02T11:00:00+03:00",
           attendees=[{"self": True, "responseStatus": "declined"}]),
        ev("f", "2026-11-02T10:00:00+03:00", "2026-11-02T11:00:00+03:00", transparency="transparent"),
        {"id": "ad", "summary": "x", "start": {"date": "2026-11-02"}, "end": {"date": "2026-11-03"}},
        ev("c", "2026-11-02T14:00:00+03:00", "2026-11-02T15:00:00+03:00"),
        ev("c2", "2026-11-02T15:02:00+03:00", "2026-11-02T16:00:00+03:00"),
        ev("c3", "2026-11-02T16:00:00+03:00", "2026-11-02T17:00:00+03:00"),
    ])
    out = ct.conflicts(client(fake), tz=TZ, now=NOW)
    assert len(out["overlaps"]) == 1
    o = out["overlaps"][0]
    assert {o["a"]["id"], o["b"]["id"]} == {"a", "b"} and o["overlap_minutes"] == 30
    assert len(out["back_to_back_chains"]) == 1
    assert [e["id"] for e in out["back_to_back_chains"][0]["events"]] == ["c", "c2", "c3"]
    assert out["heavy_days"] == []
    assert out["warning"]


def test_conflicts_heavy_day():
    evs = [ev(str(i), f"2026-11-03T{h:02d}:00:00+03:00", f"2026-11-03T{h + 1:02d}:30:00+03:00")
           for i, h in enumerate([8, 10, 12, 14, 16])]
    out = ct.conflicts(client(Fake(evs)), tz=TZ, now=NOW)
    assert out["heavy_days"] == [{"date": "2026-11-03", "meeting_minutes": 450}]
    assert out["overlaps"] == []


def busy(s, e):
    return {"start": s, "end": e}


def test_free_slots_weekend_hours_duration():
    # Friday 2026-11-06 start; 4 days -> Fri, Sat, Sun, Mon
    now = dt.datetime(2026, 11, 6, 6, 0, tzinfo=Z)
    fake = Fake(busy=[
        busy("2026-11-06T10:00:00+03:00", "2026-11-06T12:00:00+03:00"),
        busy("2026-11-06T12:10:00+03:00", "2026-11-06T17:00:00+03:00"),  # 10 min gap < 30
        busy("2026-11-09T09:00:00+03:00", "2026-11-09T18:00:00+03:00"),
    ])
    out = ct.free_slots(client(fake), duration_min=30, days=4, tz=TZ, now=now)
    assert [d["date"] for d in out["days"]] == ["2026-11-06", "2026-11-09"]
    fri = out["days"][0]["windows"]
    assert [(w["start"][11:16], w["end"][11:16], w["minutes"]) for w in fri] == [
        ("09:00", "10:00", 60), ("17:00", "18:00", 60)]
    assert out["days"][1]["windows"] == []
    method, url, body = fake.calls[-1]
    assert method == "POST" and url.endswith("/freeBusy") and json.loads(body)["items"] == [{"id": "primary"}]
    out = ct.free_slots(client(fake), duration_min=30, days=4, tz=TZ, skip_weekends=False, now=now)
    assert len(out["days"]) == 4 and out["days"][1]["windows"][0]["minutes"] == 540


def test_free_slots_today_clipped_to_now_and_custom_hours():
    now = dt.datetime(2026, 11, 2, 13, 20, tzinfo=Z)
    out = ct.free_slots(client(Fake()), duration_min=60, days=1, work_start="10:00", work_end="15:00", tz=TZ, now=now)
    w = out["days"][0]["windows"]
    assert len(w) == 1 and w[0]["start"].startswith("2026-11-02T13:20") and w[0]["minutes"] == 100
    with pytest.raises(ValueError):
        ct.free_slots(client(Fake()), work_start="18:00", work_end="09:00", tz=TZ)


def test_event_detail():
    fake = Fake(single=ev("e/1", "2026-11-02T10:00:00+03:00", "2026-11-02T11:00:00+03:00",
                          description="z" * 5000, status="confirmed",
                          conferenceData={"entryPoints": [{"entryPointType": "video", "uri": "https://zoom/1"}]},
                          attendees=[{"email": "a@x.com", "responseStatus": "tentative"}]))
    out = ct.event_detail(client(fake), "e/1", tz=TZ)
    e = out["event"]
    assert out["warning"] and len(e["description"]) == 2000
    assert e["meeting_link"] == "https://zoom/1"
    assert e["attendees"][0]["response_status"] == "tentative"
    assert "/events/e%2F1" in fake.calls[-1][1]
    with pytest.raises(ValueError):
        ct.event_detail(client(fake), " ")


def test_script_url_builder():
    spec = importlib.util.spec_from_file_location("get_google_refresh_token", SKILL / "scripts" / "get_google_refresh_token.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    verifier, challenge = mod.make_pkce()
    url = mod.build_auth_url("cid", "http://127.0.0.1:1234", "st", challenge)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == [challenge]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert set(q["scope"][0].split(" ")) == set(gc.REQUIRED_SCOPES)
    assert q["client_id"] == ["cid"] and q["redirect_uri"] == ["http://127.0.0.1:1234"]
