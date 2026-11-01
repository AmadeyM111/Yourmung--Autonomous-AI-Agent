"""Gmail read tools and draft preparation for the executive-assistant skill.

Pure functions over a ``GoogleClient``.  Every result that carries mail text is
wrapped by ``untrusted()``: mail is written by third parties and may contain
prompt-injection, so these tools return data only and truncate bodies.

Hard rule: this module only reads mail and creates drafts.  It has no code path
that delivers mail, edits labels, deletes or marks messages as read.
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import re
import time
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

try:  # imported both as a package module and via sys.path insertion
    from .google_client import GMAIL_API, GoogleClient, untrusted
except ImportError:  # pragma: no cover
    from google_client import GMAIL_API, GoogleClient, untrusted  # type: ignore

MAX_TRIAGE = 50
MAX_BODY_DRAFT = 20000
_ADDR_RE = re.compile(r"^[^\s@<>\",;]+@[^\s@<>\",;]+\.[^\s@<>\",;]+$")
_NOREPLY_RE = re.compile(
    r"(^|[._+-])(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|notifications?|bounce[sd]?)([._+-]|@)", re.I)
_ON_WROTE_RE = re.compile(r"^[ \t]*On [^\n]{0,250}(?:\n[^\n]{0,250})?\bwrote:[ \t]*$", re.M)


# -- small helpers -----------------------------------------------------------------------
def _headers(msg: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for h in (msg.get("payload") or {}).get("headers") or []:
        name = str(h.get("name") or "").lower()
        if name and name not in out:
            out[name] = str(h.get("value") or "")
    return out


def _addr(value: str) -> Tuple[str, str]:
    name, email = parseaddr(value or "")
    return name.strip(), email.strip().lower()


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"


def _iso(msg: Dict[str, Any], headers: Dict[str, str]) -> str:
    try:
        ms = int(msg.get("internalDate"))
        return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(headers.get("date", ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return ""


def _epoch(msg: Dict[str, Any], headers: Dict[str, str]) -> Optional[float]:
    iso = _iso(msg, headers)
    try:
        return dt.datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


def _owner_address(client: GoogleClient) -> str:
    profile = client.get(GMAIL_API + "/profile")
    return str(profile.get("emailAddress") or "").strip().lower()


def _is_bulk(headers: Dict[str, str]) -> bool:
    return bool(headers.get("list-unsubscribe")) or headers.get("precedence", "").strip().lower() in (
        "bulk", "list", "junk")


def _get_thread(client: GoogleClient, thread_id: str, fmt: str, headers: Optional[List[str]] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"format": fmt}
    if headers:
        params["metadataHeaders"] = headers
    return client.get(GMAIL_API + "/threads/" + _quote(thread_id), **params)


def _quote(value: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(value), safe="")


_META_HEADERS = ["From", "To", "Cc", "Subject", "Date", "List-Unsubscribe", "Precedence", "Reply-To", "Message-ID"]


# -- triage ------------------------------------------------------------------------------
def triage(client: GoogleClient, query: str = "in:inbox newer_than:2d", max_results: int = 25) -> Dict[str, Any]:
    limit = max(1, min(int(max_results or 25), MAX_TRIAGE))
    owner = _owner_address(client)
    listing = client.get(GMAIL_API + "/messages", q=query, maxResults=limit)
    threads: Dict[str, List[Dict[str, Any]]] = {}
    items: List[Dict[str, Any]] = []
    for ref in (listing.get("messages") or [])[:limit]:
        msg = client.get(GMAIL_API + "/messages/" + _quote(ref["id"]), format="metadata",
                         metadataHeaders=["From", "To", "Subject", "Date", "List-Unsubscribe", "Precedence", "Reply-To"])
        hdr = _headers(msg)
        tid = str(msg.get("threadId") or ref.get("threadId") or "")
        if tid and tid not in threads:
            try:
                threads[tid] = _get_thread(client, tid, "metadata", ["From"]).get("messages") or []
            except Exception:  # thread context is best effort
                threads[tid] = []
        tmsgs = threads.get(tid) or []
        from_name, from_email = _addr(hdr.get("from", ""))
        labels = set(msg.get("labelIds") or [])
        awaiting = False
        replied_to_owner = False
        if tmsgs:
            awaiting = _addr(_headers(tmsgs[-1]).get("from", ""))[1] != owner
            ids = [m.get("id") for m in tmsgs]
            idx = ids.index(msg.get("id")) if msg.get("id") in ids else len(tmsgs) - 1
            replied_to_owner = from_email != owner and any(
                _addr(_headers(m).get("from", ""))[1] == owner for m in tmsgs[:idx])
        parts = (msg.get("payload") or {}).get("parts") or []
        items.append({
            "message_id": str(msg.get("id") or ref["id"]),
            "thread_id": tid,
            "from_name": _clip(from_name, 120),
            "from_email": from_email,
            "to_count": len([a for a in getaddresses([hdr.get("to", "")]) if a[1]]),
            "subject": _clip(hdr.get("subject", ""), 200),
            "date": _iso(msg, hdr),
            "snippet": _clip(html.unescape(str(msg.get("snippet") or "")), 240),
            "unread": "UNREAD" in labels,
            "important": "IMPORTANT" in labels,
            "starred": "STARRED" in labels,
            "has_attachments": any(p.get("filename") for p in parts),
            "list_unsubscribe": _is_bulk(hdr),
            "awaiting_owner": awaiting,
            "is_reply_to_owner": replied_to_owner,
        })
    return untrusted({"ok": True, "items": items})


# -- thread ------------------------------------------------------------------------------
def _decode_b64(data: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (ValueError, TypeError):
        return ""
    return raw.decode("utf-8", errors="replace")


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|blockquote)>", "\n", markup)
    text = html.unescape(re.sub(r"(?s)<[^>]*>", "", markup))
    text = text.replace("\xa0", " ")
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _walk(part: Dict[str, Any], plain: List[str], htmls: List[str], atts: List[Dict[str, Any]]) -> None:
    mime = str(part.get("mimeType") or "")
    body = part.get("body") or {}
    filename = str(part.get("filename") or "")
    if filename:
        atts.append({"name": _clip(filename, 200), "mime": mime, "size": int(body.get("size") or 0)})
    elif mime == "text/plain" and body.get("data"):
        plain.append(_decode_b64(body["data"]))
    elif mime == "text/html" and body.get("data"):
        htmls.append(_decode_b64(body["data"]))
    for sub in part.get("parts") or []:
        _walk(sub, plain, htmls, atts)


def _strip_quotes(text: str) -> str:
    match = _ON_WROTE_RE.search(text)
    if match:
        text = text[: match.start()]
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _body_text(msg: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    plain: List[str] = []
    htmls: List[str] = []
    atts: List[Dict[str, Any]] = []
    _walk(msg.get("payload") or {}, plain, htmls, atts)
    text = "\n".join(p for p in plain if p.strip())
    if not text.strip() and htmls:
        text = _html_to_text("\n".join(htmls))
    return _strip_quotes(text.replace("\r\n", "\n")), atts


def thread(client: GoogleClient, thread_id: str, max_messages: int = 8, max_chars_per_message: int = 3000) -> Dict[str, Any]:
    if not str(thread_id or "").strip():
        return {"ok": False, "error": "thread_id is required"}
    max_messages = max(1, min(int(max_messages or 8), 30))
    max_chars = max(200, min(int(max_chars_per_message or 3000), 20000))
    data = _get_thread(client, thread_id.strip(), "full")
    msgs = data.get("messages") or []
    total = len(msgs)
    out = []
    for msg in msgs[-max_messages:]:
        hdr = _headers(msg)
        text, atts = _body_text(msg)
        out.append({
            "message_id": str(msg.get("id") or ""),
            "from": _clip(hdr.get("from", ""), 300),
            "to": _clip(hdr.get("to", ""), 500),
            "cc": _clip(hdr.get("cc", ""), 500),
            "date": _iso(msg, hdr),
            "subject": _clip(hdr.get("subject", ""), 200),
            "body": _clip(text, max_chars),
            "body_truncated": len(text) > max_chars,
            "attachments": atts[:20],
        })
    return untrusted({"ok": True, "thread_id": str(data.get("id") or thread_id), "message_count": total,
                      "messages_truncated": total > len(out), "messages": out})


# -- awaiting reply ----------------------------------------------------------------------
def awaiting_reply(client: GoogleClient, older_than_days: int = 2, max_results: int = 20) -> Dict[str, Any]:
    days = max(0, int(older_than_days if older_than_days is not None else 2))
    limit = max(1, min(int(max_results or 20), MAX_TRIAGE))
    owner = _owner_address(client)
    cutoff = time.time() - days * 86400
    listing = client.get(GMAIL_API + "/messages", q=f"in:sent older_than:{days}d", maxResults=min(limit * 3, 100))
    seen: set = set()
    items: List[Dict[str, Any]] = []
    for ref in listing.get("messages") or []:
        tid = str(ref.get("threadId") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        if len(items) >= limit:
            break
        msgs = _get_thread(client, tid, "metadata", _META_HEADERS).get("messages") or []
        if not msgs:
            continue
        last = msgs[-1]
        hdr = _headers(last)
        if _addr(hdr.get("from", ""))[1] != owner or "DRAFT" in (last.get("labelIds") or []):
            continue
        sent = _epoch(last, hdr)
        if sent is None or sent > cutoff:
            continue
        if _is_bulk(hdr):
            continue
        recipients = [a for a in getaddresses([hdr.get("to", "")]) if a[1]]
        real = [(n, e.lower()) for n, e in recipients
                if e.lower() != owner and _ADDR_RE.match(e) and not _NOREPLY_RE.search(e.lower())]
        if not real:
            continue
        items.append({
            "thread_id": tid,
            "message_id": str(last.get("id") or ""),
            "to_name": _clip(real[0][0], 120),
            "to_email": real[0][1],
            "subject": _clip(hdr.get("subject", ""), 200),
            "sent_at": _iso(last, hdr),
            "days_waiting": int((time.time() - sent) // 86400),
            "message_count": len(msgs),
            "snippet": _clip(html.unescape(str(last.get("snippet") or "")), 240),
        })
    return untrusted({"ok": True, "items": items})


# -- drafts ------------------------------------------------------------------------------
def _has_crlf(*values: str) -> bool:
    return any(("\r" in v or "\n" in v or "\x00" in v) for v in values)


def create_draft_reply(client: GoogleClient, thread_id: str, body: str, to: str = "", subject: str = "",
                       cc: str = "") -> Dict[str, Any]:
    to, subject, cc = to or "", subject or "", cc or ""
    if _has_crlf(to, subject, cc, thread_id or ""):
        return {"ok": False, "error": "Refused: line breaks are not allowed in to/subject/cc."}
    if not str(thread_id or "").strip():
        return {"ok": False, "error": "thread_id is required"}
    if not isinstance(body, str) or not body.strip():
        return {"ok": False, "error": "Refused: draft body is empty."}
    if len(body) > MAX_BODY_DRAFT:
        return {"ok": False, "error": f"Refused: draft body is longer than {MAX_BODY_DRAFT} characters."}
    to, subject, cc = to.strip(), subject.strip(), cc.strip()
    if to:
        parsed = getaddresses([to])
        if len(parsed) != 1 or not _ADDR_RE.match(parsed[0][1]) or "," in to or ";" in to:
            return {"ok": False, "error": "Refused: 'to' must be one valid email address."}
        to = parsed[0][1]
    cc_list: List[str] = []
    if cc:
        for _, e in getaddresses([cc]):
            if not _ADDR_RE.match(e):
                return {"ok": False, "error": "Refused: 'cc' contains an invalid email address."}
            cc_list.append(e)

    owner = _owner_address(client)
    msgs = _get_thread(client, thread_id.strip(), "metadata", _META_HEADERS).get("messages") or []
    if not msgs:
        return {"ok": False, "error": "Thread not found or empty."}
    target = next((m for m in reversed(msgs) if _addr(_headers(m).get("from", ""))[1] != owner), None)
    ref_msg = target or msgs[-1]
    hdr = _headers(ref_msg)
    if not to:
        if target is None:
            return {"ok": False, "error": "No message from another sender in this thread; pass 'to' explicitly."}
        to = _addr(hdr.get("reply-to", "") or hdr.get("from", ""))[1]
        if not _ADDR_RE.match(to):
            return {"ok": False, "error": "Could not determine a valid recipient; pass 'to' explicitly."}
    if not subject:
        base = _headers(msgs[-1]).get("subject", "") or hdr.get("subject", "")
        base = " ".join(base.split())
        subject = base if re.match(r"(?i)^re:", base) else ("Re: " + base).strip()

    message = EmailMessage()
    message["To"] = to
    if cc_list:
        message["Cc"] = ", ".join(cc_list)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    mid = " ".join(hdr.get("message-id", "").split())
    if mid and not _has_crlf(mid):
        message["In-Reply-To"] = mid
        refs = " ".join(hdr.get("references", "").split())
        message["References"] = (refs + " " + mid).strip() if refs else mid
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    draft = client.post(GMAIL_API + "/drafts", {"message": {"raw": raw, "threadId": thread_id.strip()}})
    draft_id = str(draft.get("id") or "")
    return untrusted({
        "ok": True,
        "draft_id": draft_id,
        "to": to,
        "subject": subject,
        "gmail_url": f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}",
        "note": "Draft saved, NOT sent. Review and send it yourself in Gmail.",
    })
