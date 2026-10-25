"""Durable patch for strict Telegram update acknowledgement ordering."""

from __future__ import annotations

import pathlib
from typing import Any, Dict


MARKER = "OUROBOROS_TELEGRAM_ACK_AFTER_DELIVERY"


def patch_plugin(plugin_path: pathlib.Path | str) -> Dict[str, Any]:
    plugin = pathlib.Path(plugin_path)
    if not plugin.is_file():
        return {"ok": False, "error": f"telegram-bridge plugin.py not found at {plugin}"}
    text = plugin.read_text(encoding="utf-8")
    if MARKER in text:
        return {"ok": True, "changed": False, "path": str(plugin)}
    original = text

    replacements = [
        (
            "import httpx\n",
            f"# {MARKER}: commit update offsets only after Telegram send succeeds.\n\nimport httpx\n",
        ),
        (
            "async def _inject(api, payload: Dict[str, Any]) -> None:",
            "async def _inject(api, payload: Dict[str, Any]) -> str:",
        ),
        (
            '    port = os.environ.get("OUROBOROS_HOST_SERVICE_PORT", "8767")\n'
            "    async with httpx.AsyncClient(timeout=60) as client:\n",
            '    port = os.environ.get("OUROBOROS_HOST_SERVICE_PORT", "8767")\n'
            '    wait_for_response = bool(payload.get("wait_for_response"))\n'
            '    timeout = float(payload.get("timeout_sec") or 1800) + 30 if wait_for_response else 60\n'
            "    async with httpx.AsyncClient(timeout=timeout) as client:\n",
        ),
        (
            '        if response.status_code >= 400:\n'
            '            raise RuntimeError(f"Host inject returned HTTP {response.status_code}")\n',
            '        if response.status_code >= 400:\n'
            '            raise RuntimeError(f"Host inject returned HTTP {response.status_code}")\n'
            "        response_payload = response.json()\n",
        ),
        (
            '        api.log("warning", "Host inject refused: neither TELEGRAM_CHAT_ID nor payload chat_id is configured.")\n'
            "        return\n",
            '        api.log("warning", "Host inject refused: neither TELEGRAM_CHAT_ID nor payload chat_id is configured.")\n'
            '        return ""\n',
        ),
        (
            "    except (TypeError, ValueError):\n"
            "        pass\n\n\n"
            "def _load_offset(api) -> int:\n",
            "    except (TypeError, ValueError):\n"
            "        pass\n"
            '    return str(response_payload.get("response") or "")\n\n\n'
            "def _load_offset(api) -> int:\n",
        ),
        (
            "                for update in updates[:max_updates]:\n"
            '                    update_id = int(update.get("update_id") or 0)\n',
            "                for update in updates[:max_updates]:\n"
            "                    _save_offset(api, offset)\n"
            '                    update_id = int(update.get("update_id") or 0)\n',
        ),
        (
            "            except Exception as exc:\n"
            '                api.log("warning", f"Telegram poller transient error: {exc}")\n',
            "            except Exception as exc:\n"
            "                offset = _load_offset(api)\n"
            '                api.log("warning", f"Telegram poller transient error: {exc}")\n',
        ),
        (
            '            text = str(event.get("text") or "").strip()\n'
            "            if not text:\n"
            "                return\n",
            '            text = str(event.get("text") or "").strip()\n'
            "            if not text:\n"
            "                return\n"
            '            transport = event.get("transport") if isinstance(event.get("transport"), dict) else {}\n'
            "            if (\n"
            '                str(transport.get("delivery_task_id") or "")\n'
            '                and str(event.get("task_id") or "") == str(transport.get("delivery_task_id") or "")\n'
            "            ):\n"
            "                return\n",
        ),
    ]
    for old, new in replacements:
        text = text.replace(old, new, 1)

    old_inject = """                    await _inject(api, {
                        "text": safe_text,
                        "chat_id": chat_id,
                        "user_id": int(sender.get("id") or chat_id or 1),
                        "source": "telegram-bridge",
                        "sender_label": sender_label,
                        "transport": {
                            "kind": "telegram",
                            "conversation_id": str(chat_id),
                            "sender_label": sender_label,
                        },
                        "image_base64": image_base64,
                        "image_mime": image_mime,
                        "image_caption": safe_caption,
                    })
"""
    new_inject = """                    delivery_task_id = f"tg_{update_id}"
                    response_text = await _inject(api, {
                        "text": safe_text,
                        "chat_id": chat_id,
                        "user_id": int(sender.get("id") or chat_id or 1),
                        "source": "telegram-bridge",
                        "sender_label": sender_label,
                        "transport": {
                            "kind": "telegram",
                            "conversation_id": str(chat_id),
                            "sender_label": sender_label,
                            "delivery_task_id": delivery_task_id,
                        },
                        "client_message_id": f"telegram:{update_id}",
                        "task_metadata": {
                            "source": "telegram",
                            "transport_task_id": delivery_task_id,
                            "telegram_update_id": update_id,
                            "telegram_message_id": int(message.get("message_id") or 0),
                        },
                        "wait_for_response": True,
                        "timeout_sec": 1800,
                        "image_base64": image_base64,
                        "image_mime": image_mime,
                        "image_caption": safe_caption,
                    })
                    if not response_text.strip():
                        raise RuntimeError("Host returned an empty final response")
                    try:
                        await client.send_message(chat_id, response_text, parse_mode="HTML")
                    except Exception:
                        await client.send_message(chat_id, response_text, parse_mode="")
"""
    text = text.replace(old_inject, new_inject, 1)
    if (
        MARKER not in text
        or 'response_text = await _inject(api, {' not in text
        or "offset = _load_offset(api)" not in text
        or 'transport.get("delivery_task_id")' not in text
    ):
        return {"ok": False, "changed": False, "error": "telegram reliable-delivery patch did not match expected snippets"}
    plugin.write_text(text, encoding="utf-8")
    return {"ok": True, "changed": text != original, "path": str(plugin)}


__all__ = ["MARKER", "patch_plugin"]
