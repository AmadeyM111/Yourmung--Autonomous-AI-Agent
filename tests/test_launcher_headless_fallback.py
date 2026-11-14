"""Linux headless (no-GUI-backend) launcher browser-fallback tests (#56).

The real pywebview is NOT required: every test fakes the ``webview`` module or
the probe result (CI quick-test has no pywebview installed — same precedent as
test_launcher_sync.py / test_packaged_runtime_and_lifecycle.py which import
``launcher`` directly). All mutations of launcher module state go through
``monkeypatch`` so the tests are parallel-safe and leave no residue.
"""

import json
from pathlib import Path
import shlex
import sys
import types

import pytest


@pytest.fixture
def external_launcher(monkeypatch, tmp_path):
    """A native host owns presentation; never start or stop the live install."""
    import atexit
    import launcher

    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(launcher, "_headless", False)
    monkeypatch.setattr(launcher, "_external_ui", False)
    monkeypatch.setattr(launcher, "_external_host_update", None)
    monkeypatch.setattr(launcher, "acquire_pid_lock", lambda: True)
    monkeypatch.setattr(atexit, "register", lambda *args: None)
    monkeypatch.setattr(launcher, "_detect_headless", lambda: pytest.fail("GUI probe"))
    monkeypatch.setattr(launcher, "_prepare_windows_webview_runtime", lambda: pytest.fail("Windows GUI setup"))
    monkeypatch.setattr(launcher, "_open_browser_detached", lambda *_: pytest.fail("browser opened"))
    return launcher










class _FakeEvent:
    """Deterministic threading.Event stand-in: never blocks, records set()."""

    def __init__(self, initially_set: bool = False):
        self._set = initially_set
        self.waits: list = []

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def wait(self, timeout=None) -> bool:
        # The keep-alive loop MUST pass a timeout: an untimed wait() would park
        # forever on a live event and never reach the lifecycle-liveness check.
        assert timeout is not None, "keep-alive wait() must carry a timeout"
        self.waits.append(timeout)
        return self._set


def _install_fake_webview(monkeypatch, *, init_raises,
                          backend_module="webview.platforms.gtk",
                          renderer="webkit2"):
    """Install a fake ``webview`` + ``webview.guilib`` into sys.modules.

    The real ``guilib.initialize()`` RETURNS the chosen backend MODULE — the
    module's ``__name__`` identifies the toolkit (webview.platforms.gtk),
    while ``renderer`` names the web ENGINE and is version-drifting (round
    c11: pinned 5.4 says 'gtkwebkit2', other versions say 'webkit2'), so the
    probe keys on module identity and the fake models the representative
    engine-only renderer value."""
    fake_webview = types.ModuleType("webview")
    fake_guilib = types.ModuleType("webview.guilib")
    fake_backend = types.ModuleType(backend_module)
    fake_backend.renderer = renderer
    calls = []

    def initialize(*args, **kwargs):
        calls.append((args, kwargs))
        if init_raises is not None:
            raise init_raises
        return fake_backend

    fake_guilib.initialize = initialize
    fake_webview.guilib = fake_guilib
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setitem(sys.modules, "webview.guilib", fake_guilib)
    return calls


def _stub_headless_teardown(monkeypatch, launcher, order):
    """Recording stubs for everything _run_headless_main touches.

    ``_open_browser_detached`` is stubbed SYNCHRONOUSLY (not via the
    ``webbrowser`` module): the real helper rides a daemon thread, so a
    module-level patch would make the recorded order timing-dependent and
    could even hit the real browser module after monkeypatch teardown."""
    monkeypatch.setattr(launcher, "stop_agent", lambda: order.append("stop_agent"))
    monkeypatch.setattr(
        launcher,
        "_kill_orphaned_children",
        lambda reason="window_close": order.append(("kill_orphans", reason)),
    )
    monkeypatch.setattr(
        launcher, "release_pid_lock", lambda: order.append("release_pid_lock")
    )
    monkeypatch.setattr(
        launcher,
        "_open_browser_detached",
        lambda url: order.append(("browser", url)),
    )


# ---------------------------------------------------------------------------
# 1. _webview_ready probe
# ---------------------------------------------------------------------------














# ---------------------------------------------------------------------------
# 2/3. _run_headless_main keep-alive + teardown
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 4. Signal handlers: platform-layer registration, install-before-lifecycle
# ---------------------------------------------------------------------------


def test_platform_layer_registers_sigint_and_posix_sigterm(monkeypatch):
    """The signal surface lives in platform_layer (checklist 15): SIGINT
    everywhere, SIGTERM only where POSIX delivers it."""
    import signal as signal_mod

    from ouroboros import platform_layer

    registered = []
    monkeypatch.setattr(
        platform_layer.signal,
        "signal",
        lambda num, handler: registered.append((num, handler)),
    )
    handler = object()

    platform_layer.install_shutdown_signal_handlers(handler)

    expected = {signal_mod.SIGINT}
    if not platform_layer.IS_WINDOWS:
        expected.add(signal_mod.SIGTERM)
    assert {num for num, _h in registered} == expected
    assert all(h is handler for _num, h in registered)










# ---------------------------------------------------------------------------
# 5. First-run wizard headless path (browser onboarding behavioral pin)
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 6. Non-Linux non-regression: the probe never runs off-Linux
# ---------------------------------------------------------------------------


















