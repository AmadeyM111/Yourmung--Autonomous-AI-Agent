import base64
import json
import pathlib
import re
import sys
import time
import urllib.parse

import pytest

SKILL_DIR = pathlib.Path(__file__).resolve().parents[1] / "skills" / "exec_assistant"
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

import google_client  # noqa: E402
import mail_tools  # noqa: E402

OWNER = "me@owner.com"
NOW_MS = int(time.time() * 1000)
DAY = 86400 * 1000


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def msg(mid, tid, frm, to="me@owner.com", subject="Hello", labels=(), extra=None, age_days=0, body=None, snippet="snip"):
    headers = [{"name": "From", "value": frm}, {"name": "To", "value": to}, {"name": "Subject", "value": subject}]
    for k, v in (extra or {}).items():
        headers.append({"name": k, "value": v})
    payload = {"headers": headers}
    if body is not None:
        payload.update(body)
    return {"id": mid, "threadId": tid, "labelIds": list(labels), "snippet": snippet,
            "internalDate": str(NOW_MS - age_days * DAY), "payload": payload}


class Fake:
    def __init__(self, messages, threads, listing=None):
        self.messages = {m["id"]: m for m in messages}
        self.threads = threads  # tid -> [messages]
        self.listing = listing or [{"id": m["id"], "threadId": m["threadId"]} for m in messages]
        self.calls = []
        self.drafts = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url))
        if url.startswith(google_client.TOKEN_URL):
            return 200, json.dumps({"access_token": "t", "expires_in": 3600}).encode()
        path = urllib.parse.urlparse(url).path.split("/users/me", 1)[1]
        if path == "/profile":
            return 200, json.dumps({"emailAddress": OWNER}).encode()
        if path == "/messages":
            return 200, json.dumps({"messages": self.listing}).encode()
        if path.startswith("/messages/"):
            return 200, json.dumps(self.messages[path.split("/")[2]]).encode()
        if path.startswith("/threads/"):
            tid = path.split("/")[2]
            return 200, json.dumps({"id": tid, "messages": self.threads[tid]}).encode()
        if path == "/drafts" and method == "POST":
            self.drafts.append(json.loads(body))
            return 200, json.dumps({"id": "d123", "message": {"id": "m9"}}).encode()
        return 404, b"{}"


def client_for(fake):
    values = {k: "x" for k in google_client.SETTING_KEYS}
    return google_client.GoogleClient(lambda: values, transport=fake)


def triage_fixture():
    a1 = msg("a1", "ta", "Owner <me@owner.com>", to="bob@x.com", subject="Proposal", age_days=3)
    a2 = msg("a2", "ta", "Bob <bob@x.com>", subject="Re: Proposal", labels=("UNREAD", "IMPORTANT", "STARRED"),
             body={"parts": [{"filename": "f.pdf", "mimeType": "application/pdf", "body": {"size": 5}}]})
    n1 = msg("n1", "tn", "News <news@list.com>", subject="Weekly " + "x" * 300,
             extra={"List-Unsubscribe": "<mailto:u@list.com>"}, labels=("UNREAD",), snippet="a &amp; b")
    o1 = msg("o1", "to", "Alice <alice@x.com>", subject="Sent already")
    o2 = msg("o2", "to", "Owner <me@owner.com>", to="alice@x.com", subject="Re: Sent already")
    threads = {"ta": [a1, a2], "tn": [n1], "to": [o1, o2]}
    return Fake([a2, n1, o1], threads)


def test_triage_signals():
    fake = triage_fixture()
    res = mail_tools.triage(client_for(fake))
    assert res["ok"] and res["warning"] == google_client.UNTRUSTED_NOTE
    items = {i["message_id"]: i for i in res["items"]}
    person, news, done = items["a2"], items["n1"], items["o1"]
    assert person["from_email"] == "bob@x.com" and person["from_name"] == "Bob"
    assert person["unread"] and person["important"] and person["starred"] and person["has_attachments"]
    assert person["awaiting_owner"] is True and person["is_reply_to_owner"] is True
    assert person["list_unsubscribe"] is False
    assert news["list_unsubscribe"] is True and news["unread"] and len(news["subject"]) <= 200
    assert news["snippet"] == "a & b" and news["is_reply_to_owner"] is False
    assert done["awaiting_owner"] is False
    assert person["date"].endswith("+00:00")
    assert "body" not in person
    json.dumps(res)


def test_triage_caps_max_results():
    fake = triage_fixture()
    mail_tools.triage(client_for(fake), max_results=500)
    assert any("maxResults=50" in u for _, u in fake.calls)


def _full(mid, tid, frm, body, extra=None):
    return msg(mid, tid, frm, body=body, extra=extra)


def test_thread_multipart_prefers_plain_and_strips_quotes():
    plain = "Thanks, sounds good.\n\n> old quoted line\n> more\nOn Mon, Jan 5, 2026 at 9:00 AM Bob <bob@x.com> wrote:\n> hi\n"
    m = _full("m1", "t1", "Bob <bob@x.com>", {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": b64(plain)}},
            {"mimeType": "text/html", "body": {"data": b64("<p>HTML VERSION</p>")}},
            {"mimeType": "application/pdf", "filename": "deck.pdf", "body": {"size": 1234, "attachmentId": "x"}},
        ]})
    fake = Fake([m], {"t1": [m]})
    res = mail_tools.thread(client_for(fake), "t1")
    out = res["messages"][0]
    assert out["body"] == "Thanks, sounds good."
    assert out["attachments"] == [{"name": "deck.pdf", "mime": "application/pdf", "size": 1234}]
    assert out["body_truncated"] is False and res["warning"]


def test_thread_html_only_and_truncation_and_order():
    html_doc = "<html><style>p{}</style><body><p>Hello&nbsp;<b>Tom</b> &amp; co</p><div>Line2</div></body></html>"
    m1 = _full("m1", "t1", "Bob <bob@x.com>", {"mimeType": "text/html", "body": {"data": b64(html_doc)}})
    m2 = _full("m2", "t1", "Me <me@owner.com>", {"mimeType": "text/plain", "body": {"data": b64("z" * 5000)}})
    fake = Fake([m1, m2], {"t1": [m1, m2]})
    res = mail_tools.thread(client_for(fake), "t1", max_chars_per_message=1000)
    first, second = res["messages"]
    assert [first["message_id"], second["message_id"]] == ["m1", "m2"]
    assert "Hello" in first["body"] and "Tom & co" in first["body"] and "<" not in first["body"] and "p{}" not in first["body"]
    assert second["body_truncated"] is True and len(second["body"]) <= 1000


def test_thread_limits_messages():
    ms = [_full(f"m{i}", "t1", "Bob <bob@x.com>", {"mimeType": "text/plain", "body": {"data": b64(f"b{i}")}}) for i in range(5)]
    res = mail_tools.thread(client_for(Fake(ms, {"t1": ms})), "t1", max_messages=2)
    assert [m["message_id"] for m in res["messages"]] == ["m3", "m4"]
    assert res["messages_truncated"] is True and res["message_count"] == 5


def test_awaiting_reply():
    sent_person = msg("s1", "t1", "Me <me@owner.com>", to="Bob <bob@x.com>", subject="Question", age_days=5, labels=("SENT",))
    sent_noreply = msg("s2", "t2", "me@owner.com", to="no-reply@svc.com", subject="Unsub", age_days=5)
    sent_list = msg("s3", "t3", "me@owner.com", to="bob@x.com", extra={"List-Unsubscribe": "<x>"}, age_days=5)
    sent_recent = msg("s4", "t4", "me@owner.com", to="bob@x.com", age_days=0)
    answered_q = msg("s5", "t5", "me@owner.com", to="bob@x.com", age_days=6)
    answered_r = msg("r5", "t5", "bob@x.com", age_days=4)
    threads = {"t1": [sent_person], "t2": [sent_noreply], "t3": [sent_list], "t4": [sent_recent],
               "t5": [answered_q, answered_r]}
    listing = [{"id": m, "threadId": t} for m, t in
               [("s1", "t1"), ("s2", "t2"), ("s3", "t3"), ("s4", "t4"), ("s5", "t5"), ("s1", "t1")]]
    fake = Fake([], threads, listing)
    res = mail_tools.awaiting_reply(client_for(fake), older_than_days=2)
    assert res["warning"]
    assert [i["thread_id"] for i in res["items"]] == ["t1"]
    item = res["items"][0]
    assert item["to_email"] == "bob@x.com" and item["days_waiting"] >= 4
    assert any("older_than%3A2d" in u or "older_than:2d" in u for _, u in fake.calls)


def reply_fixture():
    first = msg("m1", "t1", "Bob <bob@x.com>", subject="Plan", extra={"Message-ID": "<a@x>"})
    mine = msg("m2", "t1", "Me <me@owner.com>", to="bob@x.com", subject="Re: Plan", extra={"Message-ID": "<b@owner>"})
    last = msg("m3", "t1", "Bob <bob@x.com>", subject="Re: Plan",
               extra={"Message-ID": "<c@x>", "References": "<a@x> <b@owner>", "Reply-To": "Bobby <reply@x.com>"})
    tail = msg("m4", "t1", "Me <me@owner.com>", to="reply@x.com", subject="Re: Plan", extra={"Message-ID": "<d@owner>"})
    return first, mine, last, tail


def _raw_message(fake):
    import email
    raw = fake.drafts[0]["message"]["raw"]
    return email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def test_create_draft_reply_threading_and_defaults():
    first, mine, last, tail = reply_fixture()
    fake = Fake([], {"t1": [first, mine, last, tail]})
    res = mail_tools.create_draft_reply(client_for(fake), "t1", "Sounds good, thanks!")
    assert res["ok"] and res["draft_id"] == "d123"
    assert res["to"] == "reply@x.com"
    assert res["subject"] == "Re: Plan"
    assert res["gmail_url"] == "https://mail.google.com/mail/u/0/#drafts?compose=d123"
    assert "NOT sent" in res["note"] and res["warning"]
    sent = fake.drafts[0]["message"]
    assert sent["threadId"] == "t1"
    parsed = _raw_message(fake)
    assert parsed["In-Reply-To"] == "<c@x>"
    assert parsed["References"] == "<a@x> <b@owner> <c@x>"
    assert parsed["To"] == "reply@x.com"
    assert parsed.get_payload(decode=True).decode().strip() == "Sounds good, thanks!"


def test_create_draft_reply_explicit_to_cc_subject():
    first, mine, last, tail = reply_fixture()
    fake = Fake([], {"t1": [first, last]})
    res = mail_tools.create_draft_reply(client_for(fake), "t1", "hi", to="Carol@Y.com", subject="Custom", cc="d@y.com")
    assert res["ok"] and res["to"] == "Carol@Y.com".strip() or res["to"].lower() == "carol@y.com"
    parsed = _raw_message(fake)
    assert parsed["Subject"] == "Custom" and parsed["Cc"] == "d@y.com"


@pytest.mark.parametrize("kwargs", [
    {"to": "a@b.com\r\nBcc: evil@x.com"},
    {"subject": "hi\nBcc: evil@x.com"},
    {"cc": "a@b.com\r\nBcc: evil@x.com"},
    {"to": "a@b.com, c@d.com"},
    {"to": "not-an-address"},
])
def test_create_draft_reply_rejects_bad_headers(kwargs):
    first, mine, last, tail = reply_fixture()
    fake = Fake([], {"t1": [first, last]})
    res = mail_tools.create_draft_reply(client_for(fake), "t1", "hi", **kwargs)
    assert res["ok"] is False and not fake.drafts


@pytest.mark.parametrize("body", ["", "   \n\t", "x" * 20001])
def test_create_draft_reply_rejects_bad_body(body):
    first, mine, last, tail = reply_fixture()
    fake = Fake([], {"t1": [first, last]})
    res = mail_tools.create_draft_reply(client_for(fake), "t1", body)
    assert res["ok"] is False and not fake.drafts


def test_no_double_re_prefix():
    a = msg("m1", "t1", "Bob <bob@x.com>", subject="RE: Plan", extra={"Message-ID": "<a@x>"})
    fake = Fake([], {"t1": [a]})
    assert mail_tools.create_draft_reply(client_for(fake), "t1", "ok")["subject"] == "RE: Plan"


def test_no_send_anywhere():
    fake = triage_fixture()
    c = client_for(fake)
    mail_tools.triage(c)
    mail_tools.create_draft_reply(c, "ta", "reply text")
    mail_tools.thread(c, "ta")
    mail_tools.awaiting_reply(c)
    assert fake.drafts
    for method, url in fake.calls:
        assert "/send" not in url
        assert method in ("GET", "POST")
        if method == "POST" and not url.startswith(google_client.TOKEN_URL):
            assert url.endswith("/users/me/drafts")


def test_module_source_has_no_send_or_mutation_paths():
    source = pathlib.Path(mail_tools.__file__).read_text(encoding="utf-8")
    for needle in ("/send", "drafts.send", "messages.send", ".send(", "/modify", "/trash", "/delete", "batchModify"):
        assert needle not in source, needle
    assert not re.search(r"\.(delete|put|patch)\(", source)
