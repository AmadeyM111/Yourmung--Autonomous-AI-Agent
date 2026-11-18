"""Free Light lane prepares bulky context; the reply messages stay intact on failure."""

from ouroboros.free_context_load import BRIEF_KEY, MARKER, apply_free_context_load


def _messages():
    return [
        {"role": "system", "content": [
            {"type": "text", "text": "короткий закон"},
            {"type": "text", "text": "КНИГА " + ("память " * 2000)},
        ]},
        {"role": "user", "content": "вопрос хозяина"},
    ]


def _apply(messages, usage, loader, model="deepseek::deepseek-flash", role="main"):
    return apply_free_context_load(
        messages, llm=None, accumulated_usage=usage, model=model, model_role=role,
        round_idx=0, task_id="t1", task_type="task", drive_logs=None, loader=loader,
    )


def test_free_load_keeps_short_blocks_and_user_text():
    seen = {}

    def loader(source):
        seen["n"] = len(source)
        return "Хозяин запретил пушить. Бюджет группы 2 доллара."

    usage = {}
    out = _apply(_messages(), usage, loader)
    assert seen["n"] > 4000
    assert out[1]["content"] == "вопрос хозяина"
    assert out[0]["content"][0]["text"] == "короткий закон"
    assert "Хозяин запретил пушить" in out[0]["content"][1]["text"]
    assert MARKER in out[0]["content"][1]["text"]
    assert usage[BRIEF_KEY].startswith("Хозяин запретил")


def test_second_round_reuses_brief_without_loader():
    usage = {BRIEF_KEY: "готовый бриф с запретом пуша и бюджетом"}

    def loader(_source):
        raise AssertionError("loader must not run")

    out = _apply(_messages(), usage, loader)
    assert "готовый бриф" in out[0]["content"][-1]["text"]
    assert out[1]["content"] == "вопрос хозяина"


def test_failed_load_keeps_original_and_does_not_retry():
    calls = {"n": 0}

    def loader(_source):
        calls["n"] += 1
        raise RuntimeError("rate")

    usage = {}
    original = _messages()
    assert _apply(original, usage, loader)[0]["content"] == original[0]["content"]
    assert usage[BRIEF_KEY] == ""
    assert _apply(_messages(), usage, loader)[0]["content"][1]["text"].startswith("КНИГА")
    assert calls["n"] == 1


def test_free_outage_switches_to_main_once():
    from ouroboros.free_context_load import LANE_KEY

    calls = {"main": 0}

    def free(_source):
        raise TimeoutError("timed out")

    def main(source):
        calls["main"] += 1
        assert "КНИГА" in source
        return "Хозяин запретил пушить. Бюджет группы два доллара."

    usage = {}
    out = apply_free_context_load(
        _messages(), llm=None, accumulated_usage=usage, model="deepseek::deepseek-flash",
        model_role="main", round_idx=0, task_id="t1", task_type="task", drive_logs=None,
        loader=free, fallback_loader=main,
    )
    assert "Хозяин запретил пушить" in out[0]["content"][-1]["text"]
    assert "основная модель" in out[0]["content"][-1]["text"]
    assert out[1]["content"] == "вопрос хозяина"
    assert usage[LANE_KEY] == "main"
    again = apply_free_context_load(
        _messages(), llm=None, accumulated_usage=usage, model="deepseek::deepseek-flash",
        model_role="main", round_idx=1, task_id="t1", task_type="task", drive_logs=None,
        loader=free, fallback_loader=main,
    )
    assert "Хозяин запретил пушить" in again[0]["content"][-1]["text"]
    assert calls["main"] == 1


def test_both_lanes_down_keep_original():
    def free(_source):
        return "The model is unavailable. Please try again later."

    def main(_source):
        raise RuntimeError("down")

    usage = {}
    original = _messages()
    out = apply_free_context_load(
        original, llm=None, accumulated_usage=usage, model="deepseek::deepseek-flash",
        model_role="main", round_idx=0, task_id="t1", task_type="task", drive_logs=None,
        loader=free, fallback_loader=main,
    )
    assert out[0]["content"] == original[0]["content"]
    assert usage[BRIEF_KEY] == ""


def test_unusable_brief_falls_back():
    usage = {}
    out = _apply(_messages(), usage, lambda _source: "мало")
    assert out[0]["content"][1]["text"].startswith("КНИГА")
    assert usage[BRIEF_KEY] == ""


def test_skips_free_reply_model_and_non_main_role():
    def loader(_source):
        raise AssertionError("no load")

    original = _messages()
    assert _apply(original, {}, loader, model="openrouter::nvidia/nemotron-3.5-lightning:free") is original
    assert _apply(original, {}, loader, role="light") is original


def test_already_marked_is_unchanged():
    messages = _messages()
    messages[0]["content"][0]["text"] = MARKER + " уже сжато"
    usage = {}

    def loader(_source):
        raise AssertionError("no load")

    assert apply_free_context_load(
        messages, llm=None, accumulated_usage=usage, model="deepseek::deepseek-flash",
        model_role="main", round_idx=1, task_id="t", task_type="task", drive_logs=None, loader=loader,
    ) is messages
    assert BRIEF_KEY not in usage
