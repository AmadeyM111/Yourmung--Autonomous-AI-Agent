import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "skills" / "exec_assistant"))
import briefs  # noqa: E402
from commitments import CommitmentStore  # noqa: E402
from google_client import GoogleError  # noqa: E402

NOW = dt.datetime(2026, 10, 28, 8, 30)


def _ok(*a, **k):
    return {"ok": True}


def _patch(monkeypatch, **overrides):
    for name in ("agenda", "conflicts", "free_slots"):
        monkeypatch.setattr(briefs.calendar_tools, name, overrides.get(name, _ok))
    for name in ("triage", "awaiting_reply"):
        monkeypatch.setattr(briefs.mail_tools, name, overrides.get(name, _ok))


def _boom(*a, **k):
    raise GoogleError("down")


def test_morning_isolates_failures(monkeypatch, tmp_path):
    _patch(monkeypatch, agenda=_boom, triage=lambda *a, **k: 1 / 0)
    store = CommitmentStore(tmp_path / "c.json")
    store.add("x", due="2026-10-27")
    out = briefs.morning(object(), store, now=NOW)
    assert out["agenda_today"] == {"error": "down"}
    assert "error" in out["mail"]
    assert out["conflicts"] == {"ok": True}
    assert len(out["commitments"]["overdue"]) == 1
    assert out["generated_at"].startswith("2026-10-28") and "Russian" in out["writing_guide"]


def test_evening_isolates_failures(monkeypatch, tmp_path):
    _patch(monkeypatch, awaiting_reply=_boom, free_slots=_boom)
    out = briefs.evening(object(), CommitmentStore(tmp_path / "c.json"), now=NOW)
    assert "error" in out["awaiting_reply"] and "error" in out["free_slots_tomorrow"]
    assert out["agenda_tomorrow"] == {"ok": True}
    assert out["commitments"]["open_total"] == 0
