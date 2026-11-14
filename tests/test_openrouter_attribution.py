from __future__ import annotations

import urllib.request

from ouroboros.openrouter_attribution import OPENROUTER_APP_HEADERS
from scripts.run_external_review import _probe_model_for_key


def test_external_review_probe_uses_canonical_app_attribution(monkeypatch):
    import httpx

    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "pong"}}]}

    def post(_url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(httpx, "post", post)

    assert _probe_model_for_key("secret", "openai/gpt-5.6-sol")[0] is True
    assert {
        key: captured["headers"][key] for key in OPENROUTER_APP_HEADERS
    } == OPENROUTER_APP_HEADERS


