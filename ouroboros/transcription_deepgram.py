"""Small HTTP adapter for Deepgram's prerecorded-audio transcription API.

The adapter intentionally does not depend on Deepgram's SDK.  A WAV chunk is
streamed to ``/v1/listen`` as the raw request body, so nothing is stored on
Deepgram's side beyond the request itself.
"""

from __future__ import annotations

import pathlib
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx


_LISTEN_URL = "https://api.deepgram.com/v1/listen"
_UPLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_MODEL = "nova-3"


class DeepgramTranscriptionError(RuntimeError):
    """A safe, user-presentable failure from the Deepgram STT adapter."""


class DeepgramTranscriptionClient:
    """Transcribe temporary WAV chunks with Deepgram Nova.

    ``http_client`` is injectable for deterministic tests.  When omitted, a
    short-lived :class:`httpx.Client` is created and closed for each call.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        http_client: Any | None = None,
        *,
        timeout_sec: float = 300.0,
    ) -> None:
        clean_key = str(api_key or "").strip()
        if not clean_key:
            raise ValueError("A Deepgram API key is required")
        clean_model = str(model or "").strip()
        if not clean_model:
            raise ValueError("A Deepgram transcription model is required")
        self._api_key = clean_key
        self.model = clean_model
        self._http_client = http_client
        self._timeout = httpx.Timeout(
            connect=30.0,
            read=float(timeout_sec),
            write=float(timeout_sec),
            pool=30.0,
        )

    def transcribe_file(
        self,
        path: pathlib.Path | str,
        language: str = "auto",
        diarization: bool = False,
        custom_vocabulary: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Transcribe one audio file, returning chunk-local time offsets."""
        source = pathlib.Path(path).expanduser().resolve(strict=False)
        if not source.is_file():
            raise FileNotFoundError(f"Audio chunk not found: {source.name}")
        if int(source.stat().st_size) <= 0:
            raise ValueError("Deepgram transcription chunk is empty")
        params = self._query_params(language, bool(diarization), custom_vocabulary)
        content_type = _content_type(source)
        if self._http_client is not None:
            return self._post(self._http_client, source, params, content_type)
        with httpx.Client(timeout=self._timeout) as client:
            return self._post(client, source, params, content_type)

    def _query_params(
        self,
        language: str,
        diarization: bool,
        custom_vocabulary: Sequence[str],
    ) -> list[tuple[str, str]]:
        if isinstance(custom_vocabulary, (str, bytes)):
            raise TypeError("custom_vocabulary must be a sequence of phrases")
        params: list[tuple[str, str]] = [
            ("model", self.model),
            ("smart_format", "true"),
            ("punctuate", "true"),
            ("utterances", "true"),
        ]
        clean_language = str(language or "auto").strip()
        if not clean_language or clean_language.lower() == "auto":
            params.append(("detect_language", "true"))
        else:
            params.append(("language", clean_language))
        if diarization:
            params.append(("diarize", "true"))
        for term in dict.fromkeys(str(item).strip() for item in custom_vocabulary if str(item).strip()):
            params.append(("keyterm", term))
        return params

    def _post(
        self,
        client: Any,
        source: pathlib.Path,
        params: list[tuple[str, str]],
        content_type: str,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Token {self._api_key}", "Content-Type": content_type}
        for attempt in range(3):
            response = None
            try:
                response = client.post(
                    _LISTEN_URL,
                    params=params,
                    headers=headers,
                    content=_stream_file(source),
                )
                response.raise_for_status()
                break
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is None:
                    status = getattr(response, "status_code", None)
                should_retry = isinstance(status, int) and (status == 429 or status >= 500)
                if should_retry and attempt < 2:
                    time.sleep(min(5.0, float(2 ** attempt)))
                    continue
                suffix = f" (HTTP {int(status)})" if isinstance(status, int) else ""
                # Never include response bodies, request URLs, exception messages,
                # or authentication material in this user-facing exception.
                raise DeepgramTranscriptionError(f"Deepgram request failed during transcription{suffix}") from exc
        try:
            payload = response.json()
        except Exception as exc:
            raise DeepgramTranscriptionError("Deepgram returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DeepgramTranscriptionError("Deepgram returned invalid JSON")
        requested = next((value for key, value in params if key == "language"), None)
        return _parse_response(payload, requested_language=requested, model=self.model)


def _content_type(path: pathlib.Path) -> str:
    return {
        ".ogg": "audio/ogg", ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    }.get(path.suffix.lower(), "audio/wav")


def _stream_file(path: pathlib.Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while True:
            block = handle.read(_UPLOAD_CHUNK_BYTES)
            if not block:
                return
            yield block


def _words(alternative: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    words: list[dict[str, Any]] = []
    invalid = 0
    for raw in alternative.get("words") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("punctuated_word") or raw.get("word") or "")
        try:
            start = max(0.0, float(raw.get("start")))
            end = max(0.0, float(raw.get("end")))
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not text.strip() or end < start:
            invalid += 1
            continue
        word: dict[str, Any] = {"start": start, "end": end, "word": text}
        if raw.get("speaker") is not None:
            word["speaker"] = f"SPEAKER_{int(raw['speaker']):02d}"
        words.append(word)
    words.sort(key=lambda item: (item["start"], item["end"]))
    return words, invalid


def _segments_from_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        previous = current[-1] if current else None
        if previous is not None and (
            word.get("speaker") != previous.get("speaker") or word["start"] - previous["end"] > 1.5
        ):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    segments: list[dict[str, Any]] = []
    for group in groups:
        segment: dict[str, Any] = {
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": " ".join(str(w["word"]).strip() for w in group).strip(),
            "words": group,
        }
        if group[0].get("speaker"):
            segment["speaker"] = group[0]["speaker"]
        segments.append(segment)
    return segments


def _parse_response(
    payload: dict[str, Any],
    *,
    requested_language: str | None,
    model: str,
) -> dict[str, Any]:
    channels = (payload.get("results") or {}).get("channels") or []
    channel = channels[0] if channels and isinstance(channels[0], dict) else {}
    alternatives = channel.get("alternatives") or []
    alternative = alternatives[0] if alternatives and isinstance(alternatives[0], dict) else {}
    words, invalid = _words(alternative)
    text = str(alternative.get("transcript") or "").strip()
    segments = _segments_from_words(words)
    warnings: list[str] = []
    if invalid:
        warnings.append(f"Deepgram omitted {invalid} invalid word annotation(s).")
    if not segments and text:
        segments = [{"start": 0.0, "end": 0.0, "text": text}]
        warnings.append("Deepgram returned text without usable word timestamps.")
    if not segments:
        raise DeepgramTranscriptionError("Deepgram returned an empty transcription")
    language = str(channel.get("detected_language") or requested_language or "unknown").strip()
    return {"segments": segments, "language": language, "model": model, "warnings": warnings}


__all__ = ["DEFAULT_MODEL", "DeepgramTranscriptionClient", "DeepgramTranscriptionError"]
