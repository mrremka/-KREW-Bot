"""Opt-in voice-to-text via Groq Whisper. Audio is never stored by KREW.

Only voice notes explicitly selected via /transcribe are sent to a third-party
speech provider. Groq API access requires the operator's own API key.
"""
from __future__ import annotations

import json
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

MAX_VOICE_BYTES = 5 * 1024 * 1024
MAX_VOICE_SECONDS = 120
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


class SpeechError(Exception):
    """Safe, user-facing failure without URLs, keys, or service response bodies."""


def _file_name(file_path: str) -> str:
    if (not isinstance(file_path, str) or not 1 <= len(file_path) <= 200
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", file_path)
            or any(part in ("", ".", "..") for part in file_path.split("/"))):
        raise SpeechError("Telegram вернул некорректный путь к файлу.")
    return file_path


def _multipart(audio: bytes, boundary: str) -> bytes:
    b = boundary.encode("ascii")
    return (
        b"--" + b + b'\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
        b"whisper-large-v3-turbo\r\n"
        b"--" + b + b'\r\nContent-Disposition: form-data; name="response_format"\r\n\r\n'
        b"json\r\n"
        b"--" + b + b'\r\nContent-Disposition: form-data; name="file"; filename="voice.ogg"\r\n'
        b"Content-Type: audio/ogg\r\n\r\n" + audio + b"\r\n"
        b"--" + b + b"--\r\n"
    )


def transcribe_voice(api, token: str, groq_key: str, file_id: str) -> str:
    """Fetch a small Telegram voice and transcribe it over TLS, on demand.

    Accept only Telegram's file_path from getFile; never log URL or exceptions
    from HTTP clients because Telegram URLs contain the bot token.
    """
    if not token or not groq_key or not file_id:
        raise SpeechError("Распознавание пока не настроено.")
    try:
        metadata = api.call("getFile", file_id=file_id)
    except Exception:
        raise SpeechError("Не удалось получить голосовое из Telegram.") from None
    if not isinstance(metadata, dict):
        raise SpeechError("Telegram не вернул информацию о файле.")
    if int(metadata.get("file_size") or 0) > MAX_VOICE_BYTES:
        raise SpeechError("Голосовое слишком большое (максимум 5 МБ).")
    path = _file_name(metadata.get("file_path", ""))
    url = "https://api.telegram.org/file/bot" + token + "/" + quote(path, safe="/")
    try:
        request = Request(url, headers={"User-Agent": "KREW-Voice/1"})
        with urlopen(request, timeout=20) as response:
            audio = response.read(MAX_VOICE_BYTES + 1)
    except (OSError, URLError, HTTPError, TimeoutError):
        raise SpeechError("Не удалось скачать голосовое из Telegram.") from None
    if not audio or len(audio) > MAX_VOICE_BYTES:
        raise SpeechError("Голосовое пустое или превышает лимит 5 МБ.")

    boundary = "----KREWVoice" + secrets.token_hex(12)
    payload = _multipart(audio, boundary)
    request = Request(GROQ_ENDPOINT, data=payload, method="POST",
                      headers={"Authorization": "Bearer " + groq_key,
                               "Content-Type": "multipart/form-data; boundary=" + boundary,
                               "User-Agent": "KREW-Voice/1"})
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read(128 * 1024))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise SpeechError("Неверный ключ распознавания — проверь GROQ_API_KEY.") from None
        if exc.code == 429:
            raise SpeechError("Сервис распознавания ограничил запросы. Попробуй позже.") from None
        raise SpeechError("Сервис распознавания временно недоступен.") from None
    except (OSError, URLError, TimeoutError, ValueError):
        raise SpeechError("Не удалось распознать голосовое. Попробуй позже.") from None
    text = result.get("text", "") if isinstance(result, dict) else ""
    if not isinstance(text, str) or not text.strip():
        raise SpeechError("В голосовом не удалось распознать речь.")
    return text.strip()[:3300]
