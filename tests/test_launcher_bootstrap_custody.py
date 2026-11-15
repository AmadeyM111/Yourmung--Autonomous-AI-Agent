"""Early tray Panic in a cold interpreter must reach stop owners and its active bootstrap tree."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ouroboros import launcher_bootstrap as boot

REPO = Path(__file__).resolve().parents[1]


def test_bootstrap_run_keeps_subprocess_result_and_timeout_contract():
    stopped = threading.Event()
    result = boot.run_bootstrap_command([sys.executable, '-c', 'import sys; print(sys.stdin.read())'],
                                        stopped, input='hello', capture_output=True, text=True, check=True)
    assert result.returncode == 0 and result.stdout == 'hello\n' and result.stderr == ''
    with pytest.raises(subprocess.CalledProcessError) as failed:
        boot.run_bootstrap_command([sys.executable, '-c', 'raise SystemExit(3)'], stopped, check=True)
    assert failed.value.returncode == 3
    with pytest.raises(subprocess.TimeoutExpired):
        boot.run_bootstrap_command([sys.executable, '-c', 'import time; time.sleep(3)'], stopped, timeout=0.05)
    assert boot._BOOTSTRAP_COMMANDS == []
    stopped.set()
    with pytest.raises(InterruptedError):
        boot.run_bootstrap_command([sys.executable, '-c', 'raise SystemExit(0)'], stopped)




@pytest.mark.parametrize('windows', [False, True])
def test_interactive_installer_keeps_ordinary_terminal_and_only_panic_requests_its_stop(monkeypatch, windows):
    from ouroboros import platform_layer

    calls, stopped = [], threading.Event()
    monkeypatch.setattr(platform_layer, 'IS_WINDOWS', windows)
    proc = SimpleNamespace(pid=41)
    monkeypatch.setattr(boot, '_BOOTSTRAP_COMMANDS', [])
    monkeypatch.setattr(boot.subprocess, 'Popen', lambda command, **kw: calls.append((command, kw)) or proc)
    monkeypatch.setattr('ouroboros.platform_layer.request_process_tree_kill',
                        lambda child, **kw: calls.append(('stop', child, kw)) or {'requested': True})
    owner = boot.spawn_bootstrap_command(['installer'], stopped, interactive=True)
    assert owner['container'] is None and owner['proc'] is proc
    expected = {'creationflags': 0x08000000} if windows else {}
    assert calls == [(['installer'], expected)], 'hide the Windows console without session/group detachment or a Job'
    assert boot.stop_bootstrap_commands(include_interactive=False) == []
    assert boot.stop_bootstrap_commands() == [{'requested': True}]
    assert calls[-1] == ('stop', proc, {'job_handle': None})


@pytest.mark.parametrize('frozen', [False, True])
def test_bootstrap_runs_when_host_executable_is_a_frozen_app(monkeypatch, tmp_path, frozen):
    from ouroboros import process_containment

    python = sys.executable
    actual_container = process_containment.ProcessContainer
    lifelines = []

    def container(**kwargs):
        if 'lifeline' in kwargs:
            lifelines.append(kwargs['lifeline'])
        return actual_container(**kwargs)

    monkeypatch.setattr(process_containment, 'ProcessContainer', container)
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    if frozen:
        # A frozen app is not a Python CLI. Never execute it as the guardian.
        monkeypatch.setattr(sys, 'executable', str(tmp_path / 'not-a-python-cli'))
    result = boot.run_bootstrap_command([python, '-c', 'print("bootstrap completed")'],
                                        threading.Event(), capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout == 'bootstrap completed\n'
    assert lifelines[0] is not frozen
    assert boot._BOOTSTRAP_COMMANDS == []
