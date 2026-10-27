#!/usr/bin/env python3
"""Получение Google OAuth refresh token для навыка exec_assistant (запускает владелец, локально).

Скрипт не входит в навык и не импортируется им. Только стандартная библиотека.

Что нужно сделать один раз в Google Cloud Console (https://console.cloud.google.com/):
  1. Создайте проект (или выберите существующий).
  2. APIs & Services -> Library: включите "Gmail API" и "Google Calendar API".
  3. APIs & Services -> OAuth consent screen: тип External, добавьте себя в Test users
     (пока приложение в статусе Testing, refresh token живёт 7 дней; для постоянного
     токена переведите приложение в Production).
  4. APIs & Services -> Credentials -> Create credentials -> OAuth client ID,
     Application type = "Desktop app". Скопируйте Client ID и Client secret.

Запуск:
  python get_google_refresh_token.py --client-id XXX --client-secret YYY
  (или переменные окружения GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET)
  --no-browser  только напечатать ссылку, не открывать браузер.

В конце скрипт один раз напечатает три значения. Введите их в Settings -> Secrets:
GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN.
Токен нигде не сохраняется на диск и не пишется в логи.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _scopes():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from google_client import REQUIRED_SCOPES  # type: ignore
        return tuple(REQUIRED_SCOPES)
    except Exception:  # standalone copy of the script
        return (
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        )


REQUIRED_SCOPES = _scopes()


def make_pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(REQUIRED_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def exchange_code(client_id, client_secret, code, redirect_uri, verifier, opener=urllib.request.urlopen) -> dict:
    data = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    }).encode("ascii")
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            reason = json.loads(exc.read().decode("utf-8")).get("error_description") or exc.code
        except Exception:
            reason = exc.code
        raise SystemExit(f"Google отклонил обмен кода: {reason}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_code(port: int, state: str, timeout: float = 300.0):
    result = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in query or "error" in query:
                if query.get("state", [""])[0] != state:
                    result["error"] = "state mismatch"
                elif "error" in query:
                    result["error"] = query["error"][0]
                else:
                    result["code"] = query["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("Готово, можно закрыть вкладку и вернуться в терминал.".encode("utf-8"))
                done.set()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):  # keep the code out of logs
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1.0
    deadline = threading.Timer(timeout, done.set)
    deadline.start()
    try:
        while not done.is_set():
            server.handle_request()
    finally:
        deadline.cancel()
        server.server_close()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--no-browser", action="store_true", help="только напечатать ссылку")
    args = parser.parse_args(argv)
    if not args.client_id or not args.client_secret:
        parser.error("нужны --client-id и --client-secret (или переменные окружения GOOGLE_OAUTH_CLIENT_ID/SECRET)")

    port = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}"
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    url = build_auth_url(args.client_id, redirect_uri, state, challenge)
    if args.no_browser:
        print("Откройте эту ссылку в браузере и разрешите доступ:\n" + url, file=sys.stderr)
    else:
        print("Открываю браузер для согласия Google...", file=sys.stderr)
        if not webbrowser.open(url):
            print("Не удалось открыть браузер, откройте ссылку вручную:\n" + url, file=sys.stderr)
    result = wait_for_code(port, state)
    if not result.get("code"):
        print(f"Не получен код авторизации: {result.get('error') or 'таймаут'}", file=sys.stderr)
        return 1
    tokens = exchange_code(args.client_id, args.client_secret, result["code"], redirect_uri, verifier)
    refresh = tokens.get("refresh_token")
    if not refresh:
        print("Google не вернул refresh_token. Отзовите доступ приложения в аккаунте Google и повторите.",
              file=sys.stderr)
        return 1
    print("Введите в Settings -> Secrets:")
    print(f"GOOGLE_OAUTH_CLIENT_ID={args.client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={args.client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={refresh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
