"""Minimal Telegram Bot API adapter: only Python standard library."""
from __future__ import annotations
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(Exception):
    def __init__(self, description: str, status_code: int = 0, retry_after: int = 0):
        super().__init__(description)
        self.description = description
        self.status_code = status_code
        self.retry_after = retry_after


class TelegramAPI:
    def __init__(self, token: str):
        if not token or ":" not in token:
            raise ValueError("Укажите BOT_TOKEN в файле .env")
        self._url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, **kwargs):
        payload = json.dumps(kwargs, ensure_ascii=False).encode("utf-8")
        request = Request(self._url + method, payload, {"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=45 if method == "getUpdates" else 18) as response:
                data = json.loads(response.read())
        except HTTPError as exc:
            try:
                error = json.loads(exc.read())
            except (ValueError, OSError):
                error = {}
            raise TelegramError(error.get("description", "Ошибка Telegram API"),
                                error.get("error_code", exc.code),
                                error.get("parameters", {}).get("retry_after", 0)) from None
        except (URLError, TimeoutError, OSError) as exc:
            # Do not include exception text: URLs can contain the bot token.
            raise TelegramError("Не удалось подключиться к Telegram API") from None
        if not data.get("ok"):
            raise TelegramError(data.get("description", "Ошибка Telegram API"), data.get("error_code", 0),
                                data.get("parameters", {}).get("retry_after", 0))
        return data.get("result")
