"""Occurrence-bound outcomes survive checkpoints but never become wire fields."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from ouroboros.tool_result_record import (
    TOOL_RESULT_RECORD_KEY as KEY, make_tool_result_record, read_tool_result_record,
)


def result_row(invocation_id="first", *, facts=None):
    execution = {
        "invocation_id": invocation_id, "tool_call_id": "reused-provider-id",
        "execution_id": "execution", "round_id": "round", "task_attempt": 2,
        "trace_ref": {"manifest_ref": {"path": f"{invocation_id}.json", "sha256": invocation_id}},
    }
    text = "Identical producer text, no outcome to parse.\r\n"
    return {
        "role": "tool", "tool_call_id": execution["tool_call_id"], "content": text,
        KEY: make_tool_result_record(execution, text, facts=facts, source_ref={"path": f"{invocation_id}.txt"}),
    }


def transcript():
    return [
        {"role": "user", "content": "Inspect the file."},
        {"role": "assistant", "content": "Reading.", "tool_calls": [{
            "id": "reused-provider-id", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({KEY: "ordinary user argument"}),
            },
        }], "reasoning_details": [{"type": "reasoning.text", "text": "Reasoning", KEY: "opaque reasoning"}]},
        result_row(facts={"status": "error", "code": "PROCESS_EXIT_NONZERO", "is_error": True, "exit_code": 17}),
    ]


def test_duplicate_provider_id_and_identical_text_keep_distinct_outcomes_after_serialization():
    first = result_row("first", facts={"status": "error", "code": "PROCESS_EXIT_NONZERO", "is_error": True, "exit_code": 17})
    second = result_row("second", facts={"status": "ok", "code": "OK", "is_error": False, "exit_code": 0})
    assert first["tool_call_id"] == second["tool_call_id"] and first["content"] == second["content"]
    # Checkpoints/continuations carry canonical JSON, including the private field.
    restored = json.loads(json.dumps([first, second]))
    records = [read_tool_result_record(row) for row in restored]
    assert [record["state"] for record in records] == ["recorded", "recorded"]
    assert [record["facts"]["exit_code"] for record in records] == [17, 0]
    assert [record["facts"]["is_error"] for record in records] == [True, False]
    assert [record["invocation"]["invocation_id"] for record in records] == ["first", "second"]
    assert [record["trace_ref"]["manifest_ref"]["path"] for record in records] == ["first.json", "second.json"]
    assert [record["source_ref"]["path"] for record in records] == ["first.txt", "second.txt"]
    records[0]["facts"]["exit_code"] = 0
    assert restored[0][KEY]["facts"]["exit_code"] == 17


@pytest.mark.parametrize("change,reason", [
    ("legacy", "record_missing"), ("text", "content_mismatch"),
    ("identity", "invocation_unrecorded"), ("call_id", "tool_result_mismatch"),
])
def test_missing_or_mismatched_binding_is_unknown(change, reason):
    row = result_row(facts={"status": "ok", "code": "OK", "is_error": False, "exit_code": 0})
    if change == "legacy":
        row.pop(KEY)
    elif change == "text":
        row["content"] = row["content"].replace("\r\n", "\n")
    elif change == "identity":
        row[KEY]["invocation"].pop("invocation_id")
    else:
        row["tool_call_id"] = "other"
    record = read_tool_result_record(row)
    assert record == {"state": "unknown", "reason": reason, "facts": {
        "status": "unknown", "code": None, "is_error": None, "exit_code": None,
    }}


def test_absent_process_exit_and_absent_outcome_are_not_success():
    unknown = read_tool_result_record(result_row())
    assert unknown["state"] == "recorded"  # The occurrence is known; its outcome is not.
    assert unknown["facts"] == {"status": "unknown", "code": None, "is_error": None, "exit_code": None}
    timeout = read_tool_result_record(result_row(facts={
        "status": "error", "code": "WAIT_ENDED", "is_error": True, "timed_out": True,
    }))
    assert timeout["facts"]["exit_code"] is None
    assert timeout["facts"]["timed_out"] is True and "killed_by_host" not in timeout["facts"]




def test_physical_backstop_preserves_nested_opaque_keys_and_model_switch_keeps_record():
    from ouroboros.llm_attempt import _physical_candidate
    from ouroboros.llm_messages import _MessageShapingMixin

    messages = transcript()
    payload = {"messages": messages, "nativeContinuation": {KEY: "provider-owned"},
               "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {
                   "type": "object", "properties": {KEY: {"type": "string"}},
               }}}]}
    original = copy.deepcopy(payload)
    physical = _physical_candidate(payload)
    assert all(KEY not in row for row in physical["messages"])
    assert physical["nativeContinuation"] == original["nativeContinuation"]
    assert physical["tools"] == original["tools"]
    assert physical["messages"][1] == original["messages"][1]
    assert payload == original
    switched = _MessageShapingMixin.sanitize_reasoning_on_model_switch(messages, "first/model", "second/model")
    assert switched[-1][KEY] == messages[-1][KEY]
    assert read_tool_result_record(switched[-1])["facts"]["exit_code"] == 17
