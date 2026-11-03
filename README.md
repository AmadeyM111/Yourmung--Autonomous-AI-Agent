# Yourmung

**Yourmung** is a personal AI executive assistant. It runs locally (Docker), talks to you
through Telegram and a web interface, reads your mail and calendar, prepares briefings and
reply drafts, and transcribes voice messages and meeting recordings.

App version: **3.0.0** (see `[tool.yourmung]` in `pyproject.toml`).
Core (agent engine): **7.9.0**.

> Yourmung is a standalone project. It is built on an open-source agent engine
> (see [Origin and license](#origin-and-license)), but the entire application layer —
> the executive assistant, the Google integration, the Telegram bridge, transcription,
> safety rules, and behavior — was developed in this repository.

## What it does

### Executive assistant
- **Calendar and mail (Google).** Daily agenda, meeting conflicts, free slots, inbox triage,
  mail threads, messages awaiting your reply, and commitments.
- **Reply drafts.** The assistant prepares the text; you decide whether to send it.
- **Morning and evening briefings** on weekdays (08:30 and 18:00, Europe/Moscow).
- **Meeting minutes** from a recording or a transcript.

It runs in **read-and-draft-only** mode: sending mail and editing the calendar are disabled.
Any outbound action requires the owner's explicit confirmation. Mail and event text is
treated as untrusted data and is never executed as instructions.

### Telegram
- Chat with the assistant in a private conversation with your bot.
- Voice messages and audio files are transcribed automatically.
- Transcripts come back to the chat as a document.
- xlsx attachments are read as spreadsheets.
- Reliable delivery: messages are not lost across restarts.

### Speech to text
The provider is chosen with `TRANSCRIPTION_PROVIDER`:

| Value | Runs on | When to choose it |
|-------|---------|-------------------|
| `deepgram` | Deepgram cloud (`nova-3`) | fast, no load on your machine |
| `gemini` | Google cloud | a cloud alternative |
| `whisperx` | locally | audio never leaves your computer |
| `local` | locally (faster-whisper) | the minimal local option |

Speaker diarization uses pyannote and is enabled separately.

### Safety
- Local or Docker only; the port is published on `127.0.0.1`.
- Access from a non-local address requires a network password (`OUROBOROS_NETWORK_PASSWORD`).
- Keys live in the Secrets section of the settings. A skill reaches them only through an
  explicit grant bound to the skill's content.
- Skills are reviewed before they can be enabled.
- The assistant does not disclose to outsiders how its internal settings work.

## Quick start (Docker)

```bash
docker compose up -d --build
```

Web interface: <http://127.0.0.1:8765> (the port is published on the local address only).
Set `OUROBOROS_NETWORK_PASSWORD` before exposing it any wider.

Optional image components are enabled with build arguments:
`OUROBOROS_INSTALL_TRANSCRIPTION=1`, `OUROBOROS_INSTALL_DIARIZATION=1`,
`OUROBOROS_INSTALL_WHISPERX=1`, `OUROBOROS_INSTALL_TRACING=1`.

### Telegram
1. Create a bot with BotFather and set `TELEGRAM_BOT_TOKEN` in the container environment.
2. Start the container with `python -m ouroboros.cli telegram` (already configured in compose).

### Google (mail and calendar)
1. In Google Cloud, create an **OAuth client of type "Desktop app"** and enable the Gmail API
   and the Calendar API.
2. Obtain a refresh token:
   `python skills/exec_assistant/scripts/get_google_refresh_token.py --client-id … --client-secret …`
3. In the web interface open **Settings → Secrets → custom keys** and add
   `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`.
4. Under **Skills**, open `exec_assistant`, **Grant** access to those three keys, and enable the skill.
5. Check it: ask in chat "what is on my calendar today", or call `exec_status`.

### Transcription
Set `TRANSCRIPTION_PROVIDER` and the key of the chosen provider (`DEEPGRAM_API_KEY`,
`GEMINI_API_KEY`; for diarization, `HF_TOKEN`). The remaining `TRANSCRIPTION_*` parameters
are listed in `ouroboros/settings_defaults.py`.

## Skills

| Skill | Purpose |
|-------|---------|
| `exec_assistant` | calendar, mail, briefings, drafts (read and drafts only) |
| `meeting_minutes` | meeting minutes |
| `research_digest` | scheduled research digest |
| `post_broadcast` | post broadcasting (disabled by default) |
| `telegram` | Telegram bridge |

## Repository layout
- `skills/` — assistant skills.
- `ouroboros/` — the agent engine and application modules (transcription, Telegram, settings).
- `prompts/SYSTEM.md` — the assistant's system behavior rules.
- `supervisor/`, `server.py` — runtime and web server.
- `docs/` — documentation; the engine technical reference is [docs/ENGINE_README.md](docs/ENGINE_README.md).
- `CHANGELOG.md` — change history.

## Development and tests
```bash
uv sync
uv run pytest
```
Rules for contributors are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Origin and license
The agent engine is the open-source [Ouroboros](https://github.com/razzant/ouroboros) project
(by Anton Razzhigaev and Andrew Kaznacheev), MIT-licensed. Yourmung uses its version 7.8.0 as
a base and extends it substantially: the executive assistant, Google, Telegram, transcription,
and safety rules.

The project is distributed under the [MIT license](LICENSE). The copyright notice in the
`LICENSE` file is preserved, as the license requires.
