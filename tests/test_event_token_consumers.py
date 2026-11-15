"""Event readers distinguish complete totals, partial lower bounds and legacy ambiguity."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from ouroboros.event_token_totals import TOKEN_COUNTERS, event_token_totals


def _row(**counts):
    return {"type": "llm_usage", "record_contract_version": 2, **counts}


def test_each_counter_has_independent_unknown_zero_and_partial_evidence():
    evidence = event_token_totals([
        _row(prompt_tokens=20, completion_tokens=None, cached_tokens=0, cache_write_tokens=3),
        _row(prompt_tokens=None, completion_tokens=4, cached_tokens=0),
    ])
    assert evidence["prompt_tokens"] == {
        "total": None, "known_total": 20, "known_count": 1, "unknown_count": 1, "legacy_zero_count": 0,
    }
    assert evidence["completion_tokens"]["known_total"] == 4
    assert evidence["completion_tokens"]["total"] is None
    assert evidence["cached_tokens"]["total"] == 0
    assert evidence["cache_write_tokens"]["known_total"] == 3
    assert evidence["cache_write_tokens"]["unknown_count"] == 1
    assert all(item["total"] is None for item in event_token_totals([]).values())


@pytest.mark.parametrize("version", [None, 1])
def test_historical_zero_is_ambiguous_and_input_rows_are_unchanged(version):
    row = {"prompt_tokens": 0, "completion_tokens": 7, "cached_tokens": 0}
    if version is not None:
        row["record_contract_version"] = version
    original = copy.deepcopy(row)
    evidence = event_token_totals([row])
    assert evidence["prompt_tokens"]["total"] is None
    assert evidence["prompt_tokens"]["legacy_zero_count"] == 1
    assert evidence["completion_tokens"]["total"] == 7
    assert evidence["cached_tokens"]["legacy_zero_count"] == 1
    assert evidence["cache_write_tokens"]["unknown_count"] == 1
    assert row == original


@pytest.mark.parametrize("bad", [None, "", "0", False, True, -1, 1.5, float("inf"), float("nan")])
def test_invalid_values_do_not_become_measured_zero(bad):
    evidence = event_token_totals([_row(**dict.fromkeys(TOKEN_COUNTERS, bad))])
    assert all(item["total"] is None and item["unknown_count"] == 1 for item in evidence.values())


def test_nested_usage_preserves_the_envelope_version():
    evidence = event_token_totals([_row(usage=dict.fromkeys(TOKEN_COUNTERS, 0))])
    assert all(item["total"] == 0 and item["known_count"] == 1 for item in evidence.values())
    evidence = event_token_totals([_row(prompt_tokens=None, usage={"prompt_tokens": 123})])
    assert evidence["prompt_tokens"]["total"] is None
    assert evidence["prompt_tokens"]["known_total"] == 0




@pytest.mark.parametrize("prompt, expected", [(None, False), (0, False), (8, True)])
def test_live_scenario_requires_positive_evidence_without_inventing_totals(prompt, expected):
    from devtools.e2e_live.scenarios import LaneContext

    rows = [_row(task_id="t", prompt_tokens=prompt), _row(task_id="t", prompt_tokens=None)]
    facts = {}
    ctx = SimpleNamespace(oracle=object(), wait_events=lambda *_: rows,
                          check=lambda name, ok, **kw: facts.update(name=name, ok=ok, **kw))
    LaneContext.check_paid_tokens(ctx, ["t"])
    assert facts["ok"] is expected
    assert facts["prompt_tokens"] is None
    assert facts["completion_tokens"] is None
    assert facts["token_evidence"]["prompt_tokens"]["known_total"] == (prompt or 0)


