"""The real provider selections partition the matrix without forgiving producer exits."""
from __future__ import annotations

import subprocess
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tests.provider_contract_ci import provider_canary_matrix
from tests.provider_release_floor import required_canary_ids


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.serial
def test_real_canary_collection_is_nonempty_disjoint_and_complete():
    # Collection executes pytest's real parametrization and marker selection, not a
    # second Python filter. Fixtures (and therefore provider calls) never execute.
    prefix = "tests/test_provider_integration.py::test_full_registry_provider_contract["
    matrix = provider_canary_matrix()
    expected = {prefix + canary.canary_id + "]" for canary in matrix}
    required = {prefix + canary_id + "]" for canary_id in required_canary_ids()}
    selections = {
        "integration": expected,
        "integration and required_provider": required,
        "integration and optional_provider": expected - required,
        "integration and provider_typo": set(),
    }
    assert required and expected - required
    for selection, wanted in selections.items():
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_provider_integration.py",
             "--collect-only", "-q", "-o", "addopts=", "-m", selection],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert done.returncode == (0 if wanted else 5), (selection, done.stdout, done.stderr)
        rows = [line for line in done.stdout.splitlines() if line.startswith(prefix)]
        assert len(rows) == len(wanted) and set(rows) == wanted, (selection, rows)










