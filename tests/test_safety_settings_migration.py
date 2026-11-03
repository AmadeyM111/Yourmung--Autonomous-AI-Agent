"""One-time, locked disk migration; later changes are independent."""
import json

import pytest


@pytest.fixture
def install(tmp_path, monkeypatch):
    from ouroboros import config
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for key in config.SETTINGS_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    return config


@pytest.mark.parametrize("old", [None, "off", "light", "full"])
def test_existing_install_copies_once_persisted_and_audited(install, old):
    cfg = install
    cfg.SETTINGS_PATH.write_text(json.dumps({} if old is None else {"OUROBOROS_SAFETY_MODE": old}))
    old = old or "full"
    before = cfg.SETTINGS_PATH.read_bytes()
    assert cfg.load_settings()["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == old  # an ordinary read: in memory alone
    assert cfg.SETTINGS_PATH.read_bytes() == before
    first = cfg.load_settings(migrate=True)  # the boot's read persists the upgrade
    assert first["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == old
    saved = json.loads(cfg.SETTINGS_PATH.read_text())
    assert saved["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == old
    saved["OUROBOROS_SAFETY_MODE"] = "full" if old != "full" else "off"
    cfg.SETTINGS_PATH.write_text(json.dumps(saved))
    assert cfg.load_settings()["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == old
    events = [json.loads(line) for line in (cfg.DATA_DIR / "logs/events.jsonl").read_text().splitlines()]
    assert len([e for e in events if e["type"] == "safety_settings_migration"]) == 1
    assert events[0]["actor"] == "migration"
    assert events[0]["value"] == old


@pytest.mark.parametrize("document", [{}, {"TOTAL_BUDGET": 71.0}])
def test_owner_raw_read_does_not_author_absent_coverage(install, document):
    from ouroboros.gateway.owner_settings import _owner_read_settings_raw

    install.SETTINGS_PATH.write_text(json.dumps(document))
    before = install.SETTINGS_PATH.read_bytes()
    for _ in range(2):
        normalized = {}
        effective = _owner_read_settings_raw(document_out=normalized)
        assert normalized == document
        assert effective["OUROBOROS_SAFETY_MODE"] == effective["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "full"
    assert install.SETTINGS_PATH.read_bytes() == before
    assert not (install.DATA_DIR / "logs/events.jsonl").exists()


@pytest.mark.parametrize("document", [["x"], "text", 5])
def test_owner_safety_decision_replaces_non_object_settings(install, document):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient
    from ouroboros.gateway.safety_settings import api_owner_safety_mode

    install.SETTINGS_PATH.write_text(json.dumps(document))
    app = Starlette(routes=[Route("/api/owner/safety-mode", api_owner_safety_mode, methods=["POST"])])
    app.state.drive_root = install.DATA_DIR
    with TestClient(app) as client:
        response = client.post("/api/owner/safety-mode", json={"kind": "consciousness", "mode": "light"})
    assert response.status_code == 200 and response.json() == {"ok": True, "safety_mode": "light"}
    assert json.loads(install.SETTINGS_PATH.read_text())["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "light"


def test_new_file_full_and_no_migration_and_malformed_preserved(install):
    cfg = install
    settings = cfg.load_settings()
    assert settings["OUROBOROS_SAFETY_MODE"] == settings["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "full"
    assert not cfg.SETTINGS_PATH.exists()
    cfg.SETTINGS_PATH.write_text("{broken")
    cfg.load_settings()
    assert cfg.SETTINGS_PATH.read_text() == "{broken"


def test_explicit_new_key_is_not_overwritten_and_is_disk_authored(install, monkeypatch):
    cfg = install
    cfg.SETTINGS_PATH.write_text(json.dumps({"OUROBOROS_SAFETY_MODE": "off", "OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "full"}))
    monkeypatch.setenv("OUROBOROS_CONSCIOUSNESS_SAFETY_MODE", "off")
    assert cfg.load_settings()["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "full"
    assert not (cfg.DATA_DIR / "logs/events.jsonl").exists()


def test_fresh_desktop_second_start_keeps_consciousness_full(install):
    cfg = install
    cfg.save_settings({"OUROBOROS_SAFETY_MODE": "light"}, onboarding_safety_default=True)
    for _ in range(2):
        settings = cfg.load_settings()
        assert settings["OUROBOROS_SAFETY_MODE"] == "light"
        assert settings["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "full"
    assert not (cfg.DATA_DIR / "logs/events.jsonl").exists()


def test_fresh_web_generic_defaults_end_full_full(install):
    cfg = install
    cfg.save_settings({"OUROBOROS_SAFETY_MODE": "full", "OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "full"})
    settings = cfg.load_settings()
    assert settings["OUROBOROS_SAFETY_MODE"] == settings["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "full"


@pytest.mark.parametrize("old", ["light", "off"])
def test_owner_raw_read_and_incidental_write_preserve_legacy_coverage(install, old):
    from ouroboros.gateway.owner_settings import _owner_read_settings_raw, _owner_update_settings, fields_on_saved_document

    cfg = install
    cfg.SETTINGS_PATH.write_text(json.dumps({"OUROBOROS_SAFETY_MODE": old}))
    before = cfg.SETTINGS_PATH.read_bytes()
    assert _owner_read_settings_raw()["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == old
    assert cfg.SETTINGS_PATH.read_bytes() == before
    _owner_update_settings(fields_on_saved_document({"TOTAL_BUDGET": 71.0}))
    assert cfg.load_settings()["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == old


@pytest.mark.parametrize("document", [
    {}, {"OUROBOROS_SAFETY_MODE": "light"},
    {"OUROBOROS_SAFETY_MODE": "off", "OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "full"},
])
def test_raw_migration_never_authorizes_a_new_coverage_lowering(install, monkeypatch, document):
    from ouroboros.gateway.owner_settings import _owner_update_settings, fields_on_saved_document

    install.SETTINGS_PATH.write_text(json.dumps(document))
    before = install.SETTINGS_PATH.read_bytes()
    monkeypatch.setenv("OUROBOROS_CONSCIOUSNESS_SAFETY_MODE", "off")
    with pytest.raises(PermissionError, match="OUROBOROS_CONSCIOUSNESS_SAFETY_MODE lowering refused"):
        _owner_update_settings(fields_on_saved_document({"OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "off"}))
    assert install.SETTINGS_PATH.read_bytes() == before


@pytest.mark.parametrize("pinned", [False, True], ids=["without-lock", "pinned-snapshot"])
def test_raw_migration_is_read_only_without_persistence_authority(install, monkeypatch, pinned):
    import hashlib

    install.SETTINGS_PATH.write_text(json.dumps({"OUROBOROS_SAFETY_MODE": "light"}))
    before = install.SETTINGS_PATH.read_bytes()
    if pinned:
        monkeypatch.setenv("OUROBOROS_SETTINGS_SHA256", hashlib.sha256(before).hexdigest())
    for _ in range(2):
        loaded = install.load_settings_lock_held(_settings_lock_held=False)
        assert loaded["OUROBOROS_CONSCIOUSNESS_SAFETY_MODE"] == "light"
    assert install.SETTINGS_PATH.read_bytes() == before
    assert not (install.DATA_DIR / "logs/events.jsonl").exists()
