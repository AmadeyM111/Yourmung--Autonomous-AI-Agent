import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "skills" / "exec_assistant"))
from commitments import CommitmentStore  # noqa: E402


def test_add_list_update_done(tmp_path):
    store = CommitmentStore(tmp_path / "c.json")
    rec = store.add("Send report", person="Anna", due="2026-10-30")
    assert rec["id"].startswith("c") and len(rec["id"]) == 9 and rec["status"] == "open"
    assert json.loads((tmp_path / "c.json").read_text())["schema_version"] == 1
    assert store.list(person="ann")[0]["id"] == rec["id"]
    store.update(rec["id"], notes="x", title="Report v2")
    done = store.done(rec["id"], note="sent")
    assert done["status"] == "done" and "sent" in done["notes"]
    assert store.list() == [] and len(store.list(status="all")) == 1


def test_validation_and_caps(tmp_path):
    store = CommitmentStore(tmp_path / "c.json")
    with pytest.raises(ValueError):
        store.add("")
    with pytest.raises(ValueError):
        store.add("x", due="tomorrow")
    rec = store.add("t" * 999, notes="n" * 9999)
    assert len(rec["title"]) == 300 and len(rec["notes"]) == 2000
    with pytest.raises(ValueError):
        store.update(rec["id"], status="bogus")
    with pytest.raises(ValueError):
        store.update(rec["id"], id="zzz")
    with pytest.raises(ValueError):
        store.update("cmissing", title="a")


def test_add_many_limit_and_atomic(tmp_path):
    store = CommitmentStore(tmp_path / "c.json")
    res = store.add_many([{"title": "a"}, {"title": "b", "due": "2026-11-01"}])
    assert len(res["ids"]) == 2
    with pytest.raises(ValueError):
        store.add_many([{"title": str(i)} for i in range(31)])
    with pytest.raises(ValueError):
        store.add_many([{"title": "ok"}, {"title": "bad", "due": "nope"}])
    assert len(store.list(status="all")) == 2  # failed batch wrote nothing
    assert not list(tmp_path.glob("*.tmp"))


def test_due_summary_snooze_overdue(tmp_path):
    store = CommitmentStore(tmp_path / "c.json")
    a = store.add("old", due="2026-10-20")
    store.add("today", due="2026-10-28")
    store.add("soon", due="2026-10-30")
    store.add("far", due="2026-12-01")
    now = dt.datetime(2026, 10, 28, 9, 0)
    s = store.due_summary(now)
    assert [i["title"] for i in s["overdue"]] == ["old"]
    assert [i["title"] for i in s["due_today"]] == ["today"]
    assert [i["title"] for i in s["due_next_3_days"]] == ["soon"]
    assert [i["title"] for i in store.list(overdue_only=True, today="2026-10-28")] == ["old"]
    store.snooze(a["id"], "2026-11-15")
    assert store.due_summary(now)["overdue"] == []


def test_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    assert CommitmentStore(p).list() == []
