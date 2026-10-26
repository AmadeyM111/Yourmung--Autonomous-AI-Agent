# Ouroboros v7.8.0 — Architecture & Reference

This present-tense map (BIBLE P6) covers structure, operation and rationale. Replace affected descriptions; keep WHYs here and mechanisms in named module docstrings, so understanding guards, review and lifecycles needs no historical search. History belongs in README.md, tags and Git.

Two helpers support [Agent Core](architecture/06-agent-core.md): `ouroboros/consciousness_view.py` projects places, counted roots and bounded recent wakes; `ouroboros/usage_origin.py` owns task usage scopes and immutable billing/cause attribution in the usage ledger.

## Chapters

- [1. High-Level Architecture](architecture/01-high-level-architecture.md)
- [2. Startup / Onboarding Flow](architecture/02-startup-onboarding-flow.md)
- [3. Web UI Pages & Buttons](architecture/03-web-ui-pages-and-buttons.md)
- [4. Server API Endpoints](architecture/04-server-api-endpoints.md)
- [5. Supervisor Loop](architecture/05-supervisor-loop.md)
- [6. Agent Core](architecture/06-agent-core.md)
- [7. Configuration (ouroboros/config.py)](architecture/07-configuration.md)
- [8. Git Branching, CI, and Build](architecture/08-git-branching-ci-and-build.md)
- [9. Shutdown & Process Cleanup](architecture/09-shutdown-and-process-cleanup.md)
- [10. Key Invariants](architecture/10-key-invariants.md)
- [11. Frozen Contracts v1 (`ouroboros/contracts/`)](architecture/11-frozen-contracts-v1.md)
- [12. Host Service, Companion Processes, and Chat IDs](architecture/12-host-service-companions-and-chat-ids.md)
- [13. External Skills Layer](architecture/13-external-skills-layer.md)

---

## Jormung fork additions

These sections describe components that exist only in the yourmung fork.

### Long-form audio transcription

`ouroboros/transcription.py` is the shared speech-to-text orchestrator for long
recordings and the short Telegram wrapper. It validates containers with PyAV,
decodes mono 16 kHz PCM incrementally and sends overlapping chunks to a single
loaded `faster-whisper` model by default; duration and detected hardware select
the local model unless overridden. WhisperX (forced alignment) is an optional
local profile (`requirements-whisperx.txt`).

- `gemini` provider (opt-in): uploads each at-most-30-minute WAV chunk to the
  Gemini Files API, calls `gemini-3.5-transcribe` via the Interactions API
  (verbatim, word timestamps) and deletes the remote file immediately. No
  automatic local-to-cloud fallback; needs `GEMINI_API_KEY`; the agent tool
  defaults to `provider=local` per request so an operator-wide setting cannot
  silently cross the cloud-consent boundary. Separate limits: `TRANSCRIPTION_GEMINI_*`.
- `deepgram` provider (opt-in, `ouroboros/transcription_deepgram.py`): streams WAV
  chunks to `/v1/listen` (`nova-3`, word timestamps, native diarization,
  `keyterm` vocabulary); needs `DEEPGRAM_API_KEY`; limits `TRANSCRIPTION_DEEPGRAM_*`.
  Short Telegram voice uses it with `TELEGRAM_STT_BACKEND=deepgram`.
- Diarization is independent of STT. Gemini/Deepgram supply request-scoped
  labels (chunk-scoped on multi-chunk input); `diarization=pyannote` runs the lazy
  optional `pyannote/speaker-diarization-community-1` pipeline once over the source
  (`requirements-diarization.txt`, `HF_TOKEN`, `PYANNOTE_METRICS_ENABLED=0`,
  `TRANSCRIPTION_PYANNOTE_MAX_DURATION_SEC` cap).
- Each completed chunk atomically updates
  `data/state/transcriptions/<job_id>/checkpoint.json`; transcript text stays out
  of tool results and logs; Markdown/TXT/JSON outputs go to the task artifact store.
- `POST /api/audio/upload` streams supported audio to `data/uploads` under its own
  limit (`OUROBOROS_AUDIO_UPLOAD_MAX_BYTES`, 1 GB), leaving the chat attachment
  limit unchanged.
- The Telegram launcher (`ouroboros/telegram_bootstrap.py`, `telegram_*_patch.py`)
  applies durable patches to the reviewed bridge: inbound `audio` objects and audio
  documents are streamed to the same upload boundary, validated with the shared PyAV
  probe and injected as attachment paths; unsupported documents, videos and stickers
  stay blocked at the transport boundary. `telegram_delivery_patch.py` hardens outbound delivery.

### Docker layout

The compose file reuses the upstream image (code in `/app`, data volume `./data:/data`)
and overrides the entrypoint to `python -m ouroboros.cli telegram`. The port is published
on `127.0.0.1` by default; publishing elsewhere requires `OUROBOROS_NETWORK_PASSWORD`.

### Fork skills

`skills/research_digest` and `skills/post_broadcast` ship with the fork alongside
the `telegram` skill; they follow the standard skill manifest/review contract.

