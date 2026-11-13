#!/usr/bin/env python3
"""Container startup hook: make the Telegram bridge turn voice/audio messages into text.

Idempotent. Patches data/skills/ouroboroshub/telegram-bridge/plugin.py so that a voice or audio
message is transcribed (Deepgram via `python -m ouroboros.local_stt`) and injected into the chat
as text instead of an opaque attachment. Afterwards it re-binds the owner_skip install record to
the new content digest, because the acceptance is bound to the exact bytes of the skill.
Never raises: a failure only means voice stays an attachment.
"""
import os
import pathlib
import sys

MARKER = "OUROBOROS_VOICE_TRANSCRIBE_PATCH"
DATA = pathlib.Path(os.environ.get("OUROBOROS_DATA_DIR", "/data"))
SLUG = "telegram-bridge"
PLUGIN = DATA / "skills" / "ouroboroshub" / SLUG / "plugin.py"

HELPER = '''# OUROBOROS_VOICE_TRANSCRIBE_PATCH
async def _voice_to_text(api, audio_path) -> str:
    """Transcribe a parked voice/audio file with Deepgram; "" on any failure."""
    import sys as _sys
    cmd = [_sys.executable, "-m", "ouroboros.local_stt", str(audio_path), "--json", "--lang",
           os.environ.get("TELEGRAM_STT_LANGUAGE") or "ru", "--provider", "deepgram"]
    env = dict(os.environ)
    try:
        proxy = telegram_proxy(pathlib.Path(api.get_state_dir()))
    except Exception:
        proxy = ""
    if proxy:
        env.update({"ALL_PROXY": proxy, "HTTPS_PROXY": proxy, "HTTP_PROXY": proxy})
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, cwd="/app", env=env)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        import json as _json
        payload = _json.loads(out.decode("utf-8", errors="replace") or "{}")
        if proc.returncode != 0 or not payload.get("ok"):
            api.log("warning", "Voice transcription failed: " + str(payload.get("error") or err[:300]))
            return ""
        return str(payload.get("text") or "").strip()
    except Exception as exc:
        api.log("warning", f"Voice transcription failed: {type(exc).__name__}")
        return ""


'''

HOOK_OLD = "        parked = await telegram_inbound.park_inbound_file(api, client, inbound)\n"
HOOK_NEW = HOOK_OLD + '''        if parked is not None and inbound.get("kind") in ("voice", "audio"):  # OUROBOROS_VOICE_TRANSCRIBE_PATCH
            _voice_text = await _voice_to_text(api, parked.spec["path"])
            if _voice_text:
                safe_text = (safe_text + "\\n\\n" if safe_text else "") + "[Голосовое сообщение, расшифровка]: " + _voice_text
                parked.cleanup()
                parked = None
            else:
                await client.send_message(chat_id, "Не удалось расшифровать голосовое сообщение.")
'''
ANCHOR = "def _make_poller(api):"


def patch() -> bool:
    text = PLUGIN.read_text(encoding="utf-8")
    if MARKER in text:
        return False
    assert HOOK_OLD in text and ANCHOR in text, "bridge plugin does not match expected snippets"
    text = text.replace(HOOK_OLD, HOOK_NEW, 1).replace(ANCHOR, HELPER + ANCHOR, 1)
    compile(text, str(PLUGIN), "exec")
    PLUGIN.write_text(text, encoding="utf-8")
    return True


def rebind() -> None:
    sys.path.insert(0, "/app")
    from ouroboros.skill_install_record import read_install_record, write_install_record
    from ouroboros.skill_loader import find_skill

    skill = find_skill(DATA, SLUG)
    record = read_install_record(DATA, SLUG)
    if skill is None or not skill.content_hash or record is None or record.get("basis") != "owner_skip":
        return
    release = dict(record.get("release") or {})
    if release.get("digest") == skill.content_hash:
        return
    release["digest"] = skill.content_hash
    record = {**record, "release": release, "base_digest": skill.content_hash}
    record.pop("updated_at", None)
    write_install_record(DATA, SLUG, record)


if __name__ == "__main__":
    try:
        changed = patch() if PLUGIN.is_file() else False
        rebind()
        print("voice patch:", "applied" if changed else "present or skipped")
    except Exception as exc:  # never block startup
        print(f"voice patch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
