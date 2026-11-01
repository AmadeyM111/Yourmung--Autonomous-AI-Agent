import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "skills" / "exec_assistant"))
import plugin  # noqa: E402

ROOT = pathlib.Path(plugin.__file__).parent
EXPECTED = {
    "exec_status", "exec_agenda", "exec_conflicts", "exec_free_slots", "exec_event", "exec_mail_triage",
    "exec_mail_thread", "exec_mail_awaiting", "exec_mail_draft_reply", "exec_commitment_add",
    "exec_commitment_add_many", "exec_commitment_list", "exec_commitment_update", "exec_commitment_done",
    "exec_brief_morning", "exec_brief_evening",
}


class FakeApi:
    def __init__(self, tmp, settings=None):
        self.tools, self.routes, self.tmp, self.settings = {}, {}, tmp, settings or {}

    def get_settings(self, keys):
        return {k: self.settings[k] for k in keys if k in self.settings}

    def get_runtime_info(self):
        return {"state_dir": str(self.tmp)}

    def register_tool(self, name, handler, description="", schema=None, timeout_sec=60):
        self.tools[name] = (handler, description, schema, timeout_sec)

    def register_route(self, path, handler, methods=("GET",)):
        self.routes[path] = handler

    def on_unload(self, fn):
        pass


def _api(tmp_path):
    api = FakeApi(tmp_path)
    plugin.register(api)
    return api


def test_all_tools_registered_and_safe(tmp_path):
    api = _api(tmp_path)
    assert set(api.tools) == EXPECTED
    assert "status" in api.routes
    for name, (_, desc, schema, timeout) in api.tools.items():
        assert "send" not in name
        assert schema["type"] == "object" and isinstance(schema["properties"], dict)
        json.dumps(schema)
        assert timeout > 0
        for req in schema.get("required", []):
            assert req in schema["properties"]
    for name in ("exec_agenda", "exec_mail_thread", "exec_mail_draft_reply"):
        d = api.tools[name][1].lower()
        assert "untrusted" in d
    assert "never sends" in api.tools["exec_mail_draft_reply"][1].lower()


def test_unconfigured_returns_helpful_error(tmp_path):
    api = _api(tmp_path)
    out = json.loads(api.tools["exec_agenda"][0]())
    assert out["ok"] is False and "GOOGLE_OAUTH_CLIENT_ID" in out["error"]
    st = json.loads(api.tools["exec_status"][0]())
    assert st["connected"] is False and len(st["missing_keys"]) == 3


def test_status_never_reveals_values(tmp_path):
    api = FakeApi(tmp_path, {"GOOGLE_OAUTH_CLIENT_ID": "SECRETID", "GOOGLE_OAUTH_CLIENT_SECRET": "s", "GOOGLE_OAUTH_REFRESH_TOKEN": "t"})
    plugin.register(api)
    raw = api.tools["exec_status"][0]()
    assert "SECRETID" not in raw and json.loads(raw)["connected"] is True


def test_commitment_tools_and_validation(tmp_path):
    api = _api(tmp_path)
    h = lambda n, **k: json.loads(api.tools[n][0](**k))  # noqa: E731
    cid = h("exec_commitment_add", title="Call Bob", due="2026-11-01")["commitment"]["id"]
    assert len(h("exec_commitment_list")["items"]) == 1
    assert h("exec_commitment_update", id=cid, snooze_until="2026-11-05")["commitment"]["due"] == "2026-11-05"
    assert h("exec_commitment_done", id=cid)["commitment"]["status"] == "done"
    bad = h("exec_commitment_add", title="x", due="soon")
    assert bad["ok"] is False and "ISO" in bad["error"]
    assert h("exec_commitment_add_many", items=[{"title": "a"}, {"title": "b"}])["count"] == 2


def test_brief_tool_survives_unconfigured_google(tmp_path):
    api = _api(tmp_path)
    out = json.loads(api.tools["exec_brief_morning"][0]())
    assert out["ok"] is True and "error" in out["agenda_today"] and "writing_guide" in out


def test_manifest():
    m = json.loads((ROOT / "skill.json").read_text())
    assert m["name"] == "exec_assistant" and set(m["env_from_settings"]) == set(plugin.SETTING_KEYS)
    assert {t["name"] for t in m["scheduled_tasks"]} == {"morning_brief", "evening_wrap"}
