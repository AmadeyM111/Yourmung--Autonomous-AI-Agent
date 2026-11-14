"""Fake-PID guard for host-service and presence tests: native process effects are denied.

Server-side replacement for the fixture that lived in the removed desktop-launcher tests.
It blocks signals, execs, spawns and process-group kills so a test using fake PIDs can
never touch a real process; any attempt fails the test at teardown."""
from __future__ import annotations

import os
import signal
import subprocess

import pytest


@pytest.fixture
def native_guard(monkeypatch):
    attempts = []
    for name in ("OUROBOROS_PLANNED_RESTART_PARENT_HANDLE", "OUROBOROS_PLANNED_RESTART_BINDING_HANDLE"):
        monkeypatch.delenv(name, raising=False)

    def denied(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("unexpected native effect in fake-PID test")

    def block(module, name):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, denied)

    for name in ("kill", "killpg", "_exit", "execl", "execle", "execlp", "execlpe", "execve", "execv",
                 "execvp", "execvpe", "posix_spawn", "posix_spawnp", "system", "popen", "startfile"):
        block(os, name)
    block(signal, "pidfd_send_signal")
    yield denied
    assert attempts == [], f"unexpected effects: {attempts}"
