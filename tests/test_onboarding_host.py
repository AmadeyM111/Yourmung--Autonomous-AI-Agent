"""One onboarding host, served by a live gateway (D-8).

These tests pin the startup REORDERING and the single wizard host:

* the managed gateway is healthy BEFORE first-run onboarding is presented, and
  every pre-server safety step still precedes the server;
* the wizard is a real page (`GET /onboarding`) reachable with no provider
  configured and no supervisor running;
* neither the launcher's nor the server's boot normalization may WRITE
  settings.json at all (a fresh install's absence is what the fresh-install
  proofs are gated on; an existing file is not a licence to rewrite it), and
  neither may the readiness probe;
* neither onboarding surface hands a stored credential back out;
* the desktop host has NO save path of its own: completion is the single atomic
  `POST /api/onboarding/complete` on every host, and that endpoint authors the
  fresh-install `OUROBOROS_SAFETY_MODE=light` while the generic save path still
  cannot lower safety;
* closing the setup window without saving stays non-fatal.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import sys
import threading
import types

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

REPO = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fake pywebview: the real one is absent in the quick-test lane (same
# precedent as test_launcher_headless_fallback.py).
# --------------------------------------------------------------------------


class _FakeHook:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _FakeWindow:
    """pywebview 5.4's window surface the setup host touches (the caption tint hooks included)."""

    def __init__(self) -> None:
        self.destroyed = False
        self.loaded_urls = []
        self.events = types.SimpleNamespace(before_show=_FakeHook(), closed=_FakeHook())

    def destroy(self) -> None:
        self.destroyed = True

    def load_url(self, url) -> None:
        self.loaded_urls.append(url)


def _install_fake_webview(monkeypatch, on_start=None):
    fake = types.ModuleType("webview")
    fake.windows = []
    fake.active_window = lambda: next((window for window in reversed(fake.windows) if not window.destroyed), None)
    fake.menu = types.ModuleType("webview.menu")
    fake.menu.Menu = lambda title, items: types.SimpleNamespace(title=title, items=items)
    fake.menu.MenuAction = lambda title, function: types.SimpleNamespace(title=title, function=function)
    fake.app_menu = []
    created: dict = {}

    def create_window(title, url=None, js_api=None, **kwargs):
        created.update({"title": title, "url": url, "js_api": js_api, **kwargs})
        window = _FakeWindow()
        created["window"] = window
        fake.windows.append(window)
        return window

    def start(*_args, **kwargs):
        created["started"] = True
        if kwargs.get("menu"):  # pywebview 5.4 retains the application menu on an empty list
            fake.app_menu = kwargs["menu"]
        if on_start is not None:
            on_start(created)

    fake.create_window = create_window
    fake.start = start
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setitem(sys.modules, "webview.menu", fake.menu)
    return created, fake


def _valid_onboarding_payload() -> dict:
    return {
        "OPENAI_API_KEY": "sk-openai-1234567890",
        "OPENROUTER_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "MINIMAX_API_KEY": "",
        "MINIMAX_REGION": "",
        "OPENAI_COMPATIBLE_BASE_URL": "",
        "OPENAI_COMPATIBLE_API_KEY": "",
        "CLOUDRU_FOUNDATION_MODELS_API_KEY": "",
        "TOTAL_BUDGET": 10,
        "OUROBOROS_PER_TASK_COST_USD": 20,
        "OUROBOROS_REVIEW_ENFORCEMENT": "advisory",
        # `light` is the LOWEST runtime rank, so this payload can never trip the
        # elevation ratchet on a process whose baseline another test pinned.
        "OUROBOROS_RUNTIME_MODE": "light",
        "OUROBOROS_SKILLS_REPO_PATH": "",
        "LOCAL_MODEL_SOURCE": "",
        "LOCAL_MODEL_FILENAME": "",
        "LOCAL_MODEL_CONTEXT_LENGTH": 16384,
        "LOCAL_MODEL_N_GPU_LAYERS": -1,
        "LOCAL_MODEL_CHAT_FORMAT": "",
        "LOCAL_ROUTING_MODE": "cloud",
        "OUROBOROS_MODEL": "openai::gpt-5.6-terra",
        "OUROBOROS_MODEL_HEAVY": "",
        "OUROBOROS_MODEL_LIGHT": "",
        "OUROBOROS_MODEL_FALLBACKS": "",
    }


# --------------------------------------------------------------------------
# 1. Startup ordering: gateway first, onboarding after
# --------------------------------------------------------------------------








# --------------------------------------------------------------------------
# 2. The setup window loads the live page
# --------------------------------------------------------------------------














# --------------------------------------------------------------------------
# 3. Fresh-install proofs
# --------------------------------------------------------------------------








def test_server_boot_never_writes_the_settings_file():
    """The server's boot normalization is APPLIED in-process and persisted
    nowhere (spec 4.3.5: start-time mutators are retired). Every reader
    re-derives the same normalization through the shared read seam, so a
    start-time write would only make boot a second author of settings.json —
    on a host where the server now starts BEFORE first-run onboarding, that
    author would create the file the wizard is proved not to have yet."""
    import ast
    import textwrap

    import server

    source = inspect.getsource(server.lifespan)
    tree = ast.parse(textwrap.dedent(source))

    # Asserted on the syntax, not on the text: a comment that merely mentions
    # save_settings must not be able to fail or to satisfy this.
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "save_settings" not in called
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "SETTINGS_PATH" not in imported
    # The normalization still runs, still reaches the environment, and only then
    # is the owner's runtime-mode baseline pinned against it.
    applied_at = source.index("apply_runtime_provider_defaults(load_settings(migrate=True))")
    env_at = source.index("_apply_settings_to_env(settings)")
    baseline_at = source.index("initialize_runtime_mode_baseline()")
    assert applied_at < env_at < baseline_at


def test_server_boot_leaves_the_settings_bytes_alone(tmp_path, monkeypatch):
    """The behavioural half of the pin above. A REAL lifespan boot over a document
    whose provider normalization reports a change (a product-authored Heavy default
    the normalization clears — the kind of change the retired boot write persisted)
    leaves the file's bytes and mtime untouched. The syntactic pin is the fast
    tripwire; this one also catches a boot write that reaches the disk through some
    helper other than the named saver.

    The boot managed-update thread is the one lifespan job stubbed for a reason of its
    own rather than for scope: it is a daemon whose work races this assertion anyway,
    and it reaches for the MANAGED REPO — running it would have this pin fetch from
    whatever ``REPO_DIR`` resolves to in the process that happens to run pytest."""
    import server as srv
    from ouroboros import config as cfg
    from ouroboros.server_runtime import apply_runtime_provider_defaults

    document = {"OUROBOROS_MODEL_HEAVY": "anthropic/claude-opus-" + "4.7",
                "OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "full"}
    assert apply_runtime_provider_defaults(dict(document))[1] is True, (
        "the fixture must give boot something it could persist")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(cfg, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.delenv("OUROBOROS_MODEL", raising=False)
    drive_root = tmp_path / "drive"
    drive_root.mkdir()
    # ``srv.app`` is the auth-gate wrapper; the inner Starlette state carries the roots.
    monkeypatch.setattr(srv.app.app.state, "drive_root", drive_root, raising=False)
    monkeypatch.setattr(srv.app.app.state, "repo_dir", tmp_path / "repo", raising=False)

    class _NoServer:
        def __init__(self, _config):
            self.should_exit = False

        async def serve(self):
            return None

    # Everything the boot segment does NOT own is stubbed; the settings read, the
    # provider normalization and any writer stay real, which is the point.
    monkeypatch.setattr(srv, "_apply_settings_to_env", lambda *_a, **_k: None)
    monkeypatch.setattr(srv, "has_startup_ready_provider", lambda *_a, **_k: False)
    monkeypatch.setattr("ouroboros.server_runtime.has_local_routing", lambda *_a, **_k: False)
    monkeypatch.setattr(srv, "_start_supervisor_if_needed", lambda *_a, **_k: None)
    monkeypatch.setattr(srv, "_boot_managed_update_tasks", lambda *_a, **_k: None)
    monkeypatch.setattr(srv.uvicorn, "Server", _NoServer)
    monkeypatch.setattr("ouroboros.launcher_bootstrap.ensure_data_skills_seeded", lambda: None)
    monkeypatch.setattr("ouroboros.server_auth.get_configured_network_password", lambda: "")
    before = settings_path.read_bytes()
    before_mtime = settings_path.stat().st_mtime_ns
    running = set(threading.enumerate())

    with TestClient(srv.app):
        pass
    # The lifespan hands the drive root to its import owner, a daemon that then runs the steps
    # waiting on publication; a slow runner is still inside them when the client closes.
    for thread in set(threading.enumerate()) - running:
        if thread.name in ("current-store-import", "store-ready-steps"):
            thread.join(60)

    assert settings_path.read_bytes() == before, "boot rewrote the settings document"
    assert settings_path.stat().st_mtime_ns == before_mtime


# --------------------------------------------------------------------------
# 4. The served wizard host
# --------------------------------------------------------------------------


def _routes_app(tmp_path):
    from ouroboros.gateway.router import collect_routes

    app = Starlette(routes=collect_routes(data_dir=tmp_path))
    app.state.drive_root = tmp_path
    return app


def test_onboarding_page_is_served_without_a_provider_or_a_supervisor(monkeypatch, tmp_path):
    """No provider configured, no supervisor in this process at all: the wizard
    host is still reachable, because a gateway without a supervisor is a normal
    runtime state (ARCHITECTURE §2)."""
    from ouroboros.gateway import onboarding_host

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(onboarding_host, "load_settings", lambda: {})

    with TestClient(_routes_app(tmp_path)) as client:
        response = client.get("/onboarding")

    assert response.status_code == 200
    assert 'src="/onboarding/static/modules/onboarding_wizard.js"' in response.text
    assert 'href="/onboarding/static/onboarding.css"' in response.text
    assert "__OURO_ONBOARDING_BOOTSTRAP__" in response.text
    assert response.headers["cache-control"] == "no-store"
    # Side-effect-free: serving the page authors nothing.
    assert not settings_path.exists()


def test_onboarding_readiness_probe_still_gates_the_blocking_overlay(monkeypatch, tmp_path):
    from ouroboros.gateway import settings as gw_settings

    monkeypatch.setattr(gw_settings, "load_settings", lambda: {})
    with TestClient(_routes_app(tmp_path)) as client:
        unconfigured = client.get("/api/onboarding")
    assert unconfigured.status_code == 200

    monkeypatch.setattr(
        gw_settings, "load_settings", lambda: {"OPENROUTER_API_KEY": "sk-or-v1-configured"}
    )
    with TestClient(_routes_app(tmp_path)) as client:
        configured = client.get("/api/onboarding")
    assert configured.status_code == 204


# --------------------------------------------------------------------------
# 4b. Neither onboarding surface may write, and neither may serve a credential.
#
# Self-contained on purpose (own app builder, own imports): these guard a
# defect that was live on this branch, and the completion branch is rewriting
# the section above them. A merge that drops their helper must fail loudly
# instead of quietly deleting the proof.
# --------------------------------------------------------------------------


def _onboarding_client(tmp_path):
    from starlette.applications import Starlette as _Starlette
    from starlette.testclient import TestClient as _TestClient

    from ouroboros.gateway.router import collect_routes

    app = _Starlette(routes=collect_routes(data_dir=tmp_path))
    app.state.drive_root = tmp_path
    return _TestClient(app)


def test_the_readiness_probe_never_authors_settings_json(monkeypatch, tmp_path):
    """A GET must never be the first author of settings.json (D-8).

    The fixture is the case that actually persisted: a fresh local-first install
    whose normalization changes a value (today the retired shipped Heavy default it
    clears). That write created the file before the owner had answered anything,
    destroying the fresh-install proof the install presets and the `light` safety
    default are both gated on.
    """
    from ouroboros.config import SETTINGS_DEFAULTS
    from ouroboros.gateway import settings as gw_settings
    from ouroboros.server_runtime import apply_runtime_provider_defaults

    settings_path = tmp_path / "settings.json"
    saves: list = []
    fresh_local_first = dict(SETTINGS_DEFAULTS)
    fresh_local_first["LOCAL_MODEL_SOURCE"] = "Qwen/Qwen2.5-7B-Instruct-GGUF"
    fresh_local_first["OUROBOROS_MODEL_HEAVY"] = "google/gemini-3.5-flash"

    # Normalization must still have something to change, or the fixture would
    # prove nothing about persistence.
    _normalized, changed, _keys = apply_runtime_provider_defaults(dict(fresh_local_first))
    assert changed is True

    monkeypatch.setattr(gw_settings, "load_settings", lambda: dict(fresh_local_first))
    monkeypatch.setattr(
        gw_settings, "save_settings",
        lambda *a, **k: (saves.append(a), settings_path.write_text("{}", encoding="utf-8")),
        raising=False,
    )
    with _onboarding_client(tmp_path) as client:
        assert client.get("/api/onboarding").status_code == 200

    assert saves == []
    assert not settings_path.exists()


def test_onboarding_page_route_is_declared_on_the_gateway_boundary():
    from ouroboros.gateway.contracts import HTTP_ENDPOINTS

    assert "GET /onboarding" in HTTP_ENDPOINTS
    assert "GET /api/onboarding" in HTTP_ENDPOINTS
    assert "POST /api/onboarding/subagents/preview" in HTTP_ENDPOINTS
    # The page and the atomic completion it posts to are both on the boundary:
    # every host now finishes through the same one transaction.
    assert "POST /api/onboarding/complete" in HTTP_ENDPOINTS


_SECRET_CANARIES = {
    "OPENROUTER_API_KEY": "sk-or-SECRETCANARY123",
    "OPENAI_API_KEY": "sk-openai-SECRETCANARY124",
    "OPENAI_COMPATIBLE_API_KEY": "compat-SECRETCANARY125",
    "CLOUDRU_FOUNDATION_MODELS_API_KEY": "cloudru-SECRETCANARY126",
    "MINIMAX_API_KEY": "minimax-SECRETCANARY127",
    "ANTHROPIC_API_KEY": "sk-ant-SECRETCANARY128",
    "GIGACHAT_CREDENTIALS": "giga-SECRETCANARY129",
    "GIGACHAT_PASSWORD": "gigapw-SECRETCANARY130",
    "GITHUB_TOKEN": "ghp-SECRETCANARY131",
    "OUROBOROS_NETWORK_PASSWORD": "netpw-SECRETCANARY132",
}


def _leaked(text: str) -> list:
    return sorted(key for key, value in _SECRET_CANARIES.items() if value in text)


def test_the_onboarding_page_route_serves_no_stored_credential(monkeypatch, tmp_path):
    """`GET /onboarding` is unauthenticated on every host and has no startup
    gate at all — it always serves. On a supported non-loopback bind with no
    OUROBOROS_NETWORK_PASSWORD, anything in that page is readable by anyone on
    the LAN, so a stored credential must not be in it."""
    from ouroboros.gateway import onboarding_host

    monkeypatch.setattr(onboarding_host, "load_settings", lambda: dict(_SECRET_CANARIES))
    with _onboarding_client(tmp_path) as client:
        response = client.get("/onboarding")

    assert response.status_code == 200
    assert _leaked(response.text) == []
    # …and the page still tells the wizard the providers ARE configured.
    assert "***set***" in response.text


def test_the_readiness_probe_body_serves_no_stored_credential(monkeypatch, tmp_path):
    """`GET /api/onboarding` answers 204 once the startup gate passes, so the
    stored credential reachable through its wizard body is one that does not
    satisfy that gate — an OpenAI-compatible KEY with no base URL. Same class,
    second route."""
    from ouroboros.gateway import settings as gw_settings

    stored = {"OPENAI_COMPATIBLE_API_KEY": _SECRET_CANARIES["OPENAI_COMPATIBLE_API_KEY"]}
    monkeypatch.setattr(gw_settings, "load_settings", lambda: dict(stored))
    with _onboarding_client(tmp_path) as client:
        response = client.get("/api/onboarding")

    assert response.status_code == 200
    assert _leaked(response.text) == []
    assert "***set***" in response.text


# --------------------------------------------------------------------------
# 5. Completion seam
# --------------------------------------------------------------------------


def test_completion_is_the_single_atomic_endpoint_on_every_host():
    """D-8 closed. The page posts ONE transaction and has no second way to
    finish: not the `POST /api/settings` + `POST /api/owner/runtime-mode` pair
    whose failure between the two writes left providers saved and runtime mode
    not, and not the desktop `save_wizard` bridge, whose only reason to exist
    (authoring the fresh-install `light` safety default) the endpoint now
    discharges itself.

    CHANGED EXPECTATION: this test previously REQUIRED both fallbacks, because
    the endpoint did not exist in the branch that wrote it. It does now, so the
    fallbacks were the last thing keeping a first run able to take a
    non-atomic path."""
    source = (REPO / "web/modules/onboarding_wizard.js").read_text(encoding="utf-8")
    # The absence assertions read CODE, not prose: the module documents the two
    # removed paths by name, and a comment must not be able to fail the gate
    # (nor to satisfy it).
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//"))

    assert "const ONBOARDING_COMPLETE_ENDPOINT = '/api/onboarding/complete';" in code
    assert "const result = await completeOnboardingAtomically(payload);" in code
    assert "saveWizardThroughDesktopBridge" not in code
    assert "saveWizardThroughSettingsPair" not in code
    assert "save_wizard" not in code
    assert "/api/owner/runtime-mode" not in code
    assert "'/api/settings'" not in code
    # A missing route is now a real error, not a signal to take another path.
    assert "response.status === 404" not in code
    # One completion announcer for all three shells (that part is unchanged).
    assert "function announceCompletion(result)" in source
    assert "ouroboros:onboarding-complete" in source
    assert "window.pywebview.api.onboarding_finished" in source


def test_the_atomic_completion_route_is_declared_wherever_it_is_implemented(tmp_path):
    """Gateway-boundary invariant that survives the merge either way: the
    contract and the router agree about the atomic endpoint. Phase 3A hosts the
    wizard and does not implement it; the presets branch does. Both states are
    valid — a contract that disagrees with the router never is."""
    from ouroboros.gateway import router
    from ouroboros.gateway.contracts import HTTP_ENDPOINTS

    declared = "POST /api/onboarding/complete" in HTTP_ENDPOINTS
    mounted = any(
        getattr(route, "path", "") == "/api/onboarding/complete"
        for route in router.collect_routes(data_dir=tmp_path)
    )

    assert declared == mounted


# --------------------------------------------------------------------------
# 6. D-1: the startup gate is untouched
# --------------------------------------------------------------------------


def test_a_subscription_can_never_satisfy_the_startup_provider_gate():
    """D-1: `has_startup_ready_provider` stays a structural API-key/local-routing
    predicate. Agent subscriptions live in the Claudexor daemon and contribute
    nothing to it — connecting one during onboarding must not unlock startup."""
    from ouroboros.server_runtime import has_startup_ready_provider

    assert has_startup_ready_provider({}) is False
    assert has_startup_ready_provider({"OUROBOROS_SUBAGENT_HARNESS": "claude=claude-opus-5"}) is False
    assert has_startup_ready_provider({"OUROBOROS_REVIEWER_SLOTS": '{"triad": []}'}) is False
    assert has_startup_ready_provider({"LOCAL_MODEL_SOURCE": "Qwen/Qwen2.5-7B"}) is False
    assert has_startup_ready_provider({"OPENROUTER_API_KEY": "sk-or-v1-x"}) is True
    assert has_startup_ready_provider({"USE_LOCAL_MAIN": True}) is True
