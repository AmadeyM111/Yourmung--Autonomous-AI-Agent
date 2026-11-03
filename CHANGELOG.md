# Changelog

История изменений проекта. Старые подробные release rows также сохранены в
`README.md`, git tags и GitHub Releases.

## 3.0.1 - Core upgraded to upstream v7.9.0

Ядро Ouroboros 7.8.0 → 7.9.0, форк-доработки сохранены. Детали, проверка и откат: [docs/ROLLOUT_LOG.md](docs/ROLLOUT_LOG.md).

## 2.3.0 - Rebased onto upstream v7.8.0

The fork (previously a v6.18.1 snapshot with local changes) was re-based onto
upstream `razzant/ouroboros` v7.8.0. Upstream files were taken as-is and our
intent was re-applied by hand.

### Kept (re-applied)

- Telegram bridge patches (audio attachment, delivery, local STT, subscription menu).
- Audio transcription: local faster-whisper, WhisperX, Gemini, Deepgram; pyannote
  diarization; `POST /api/audio/upload`.
- xlsx ingestion, `research_digest` and `post_broadcast` skills.
- Docker: upstream single self-contained image plus optional build args
  `OUROBOROS_INSTALL_TRANSCRIPTION|DIARIZATION|WHISPERX|TRACING`, `ffmpeg`;
  compose runs the Telegram launcher, publishes on `127.0.0.1` only,
  `OUROBOROS_NETWORK_PASSWORD` required before binding wider.
- `pyproject.toml` extras `transcription` and `tracing` (uv.lock regenerated);
  diarization/WhisperX stay in `requirements-*.txt` because they pin
  `huggingface_hub<1` and would downgrade the base lock.

### Dropped

- Google Colab bootstrap and notebooks, Groq, Ollama, Qwen-specific provider,
  minimal-context mode.
- `poetry.lock` (upstream uses uv; `uv.lock` is authoritative).
- Our edits to `tests/test_skill_review.py` (removed upstream).
- Fork-specific Russian operational docs (`docs/architecture.md`, ...) are not part
  of this port and the older 6.x entries below are historical.

## Unreleased

### Added

- Added Russian operational docs:
  - `docs/architecture.md`
  - `docs/tools.md`
  - `docs/evaluation.md`
  - `docs/runbook.md`
  - `docs/adr/`
- Added critical component maps:
  - `docs/CRITICAL_AGENT_COMPONENTS.md`
  - `docs/CRITICAL_AGENT_COMPONENTS_RU.md`

### Changed

- Documented Groq/Telegram digest failure modes: 400 tool-use failure, 413
  oversized request, and 429 provider rate limit.
- Documented primary/fallback/reserve model chain and context/output budget
  alignment for OpenAI-compatible and Ollama routes.

## 6.18.1 - 2026-06-06

### Fixed

- Kept macOS signing compatible with mobile browser checks.
- macOS packages bundle Chromium headless shell and use managed Playwright
  cache for first-use WebKit downloads.

## 6.18.0 - 2026-06-05

### Added

- Browser tools support explicit `engine=chromium|webkit` and Playwright
  device descriptors.
- Chat composer responsive toolbar and mobile control layout.
- Persisted owner-local widget card ordering.

## 6.17.0 - 2026-06-04

### Changed

- Task results moved to typed task contract, outcome axes and verification
  ledger.
- Headless/API/CLI tasks gained explicit deadlines, finalization grace and
  public result projection.

## 6.16.0 - 2026-06-04

### Added

- Server-side reconciliation for worker-enabled/disabled companion processes.

## 6.15.0 - 2026-06-04

### Added

- Out-of-process extension parity and durable extension health state.
- Host Service bridge for reviewed extension callbacks.

