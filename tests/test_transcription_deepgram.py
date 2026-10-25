from __future__ import annotations

import httpx
import pytest

from ouroboros.transcription_deepgram import DeepgramTranscriptionClient, DeepgramTranscriptionError


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.deepgram.com/v1/listen")
            raise httpx.HTTPStatusError(
                "secret detail", request=request, response=httpx.Response(self.status_code, request=request),
            )


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        kwargs["body"] = b"".join(kwargs["content"])
        self.calls.append((url, kwargs))
        return self.response


def _payload():
    return {"results": {"channels": [{"detected_language": "ru", "alternatives": [{
        "transcript": "Привет мир",
        "words": [
            {"word": "привет", "punctuated_word": "Привет", "start": 0.1, "end": 0.5, "speaker": 0},
            {"word": "мир", "punctuated_word": "мир", "start": 0.6, "end": 0.9, "speaker": 1},
        ],
    }]}]}}


def _wav(tmp_path):
    path = tmp_path / "chunk.wav"
    path.write_bytes(b"RIFFdata")
    return path


def test_transcribe_file_builds_request_and_parses_words(tmp_path):
    http = FakeClient(FakeResponse(_payload()))
    client = DeepgramTranscriptionClient("dg-key", http_client=http)
    result = client.transcribe_file(_wav(tmp_path), diarization=True, custom_vocabulary=["Ouroboros"])
    url, kwargs = http.calls[0]
    assert url == "https://api.deepgram.com/v1/listen"
    assert kwargs["headers"]["Authorization"] == "Token dg-key"
    assert kwargs["body"] == b"RIFFdata"
    params = kwargs["params"]
    assert ("model", "nova-3") in params and ("detect_language", "true") in params
    assert ("diarize", "true") in params and ("keyterm", "Ouroboros") in params
    assert result["language"] == "ru"
    assert [s["speaker"] for s in result["segments"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert result["segments"][0]["text"] == "Привет"


def test_explicit_language_disables_detection(tmp_path):
    http = FakeClient(FakeResponse(_payload()))
    DeepgramTranscriptionClient("k", http_client=http).transcribe_file(_wav(tmp_path), language="ru")
    params = http.calls[0][1]["params"]
    assert ("language", "ru") in params and ("detect_language", "true") not in params


def test_http_error_is_sanitized(tmp_path):
    client = DeepgramTranscriptionClient("dg-key", http_client=FakeClient(FakeResponse(status_code=401)))
    with pytest.raises(DeepgramTranscriptionError) as err:
        client.transcribe_file(_wav(tmp_path))
    assert str(err.value) == "Deepgram request failed during transcription (HTTP 401)"


def test_empty_result_raises(tmp_path):
    client = DeepgramTranscriptionClient("k", http_client=FakeClient(FakeResponse({"results": {}})))
    with pytest.raises(DeepgramTranscriptionError):
        client.transcribe_file(_wav(tmp_path))


def test_short_audio_uses_deepgram(tmp_path):
    from ouroboros.transcription import transcribe_short_audio

    class Stub:
        model = "nova-3"

        def transcribe_file(self, path, language="auto"):
            return {"segments": [{"start": 0.0, "end": 2.0, "text": "ok"}], "language": "ru", "model": "nova-3"}

    audio = tmp_path / "v.ogg"
    audio.write_bytes(b"x")
    result = transcribe_short_audio(audio, provider="deepgram", deepgram_client=Stub())
    assert result["text"] == "ok" and result["provider"] == "deepgram" and result["duration"] == 2.0
