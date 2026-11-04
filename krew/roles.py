"""Telegram member tags for KREW. Tags are labels, never permissions."""
from __future__ import annotations

import re

MAX_TAG_CHARS = 16
RESERVED = frozenset({
    "админ", "администратор", "администрация", "модератор",
    "владелец", "создатель", "owner", "admin", "moderator",
    "support", "поддержка",
})
EXAMPLES = ("Новичок", "Активист", "Ветеран", "VIP", "Помощник")


def clean_tag(raw: str) -> str:
    """Validate a Telegram-compatible, non-impersonating regular-member tag."""
    tag = " ".join(str(raw or "").strip().split())
    if not 1 <= len(tag) <= MAX_TAG_CHARS:
        raise ValueError("Роль должна содержать от 1 до 16 символов.")
    if not tag[0].isalnum() or not all(c.isalnum() or c in " _-" for c in tag):
        raise ValueError("В роли разрешены буквы, цифры, пробелы, - и _. Без эмодзи.")
    if tag.casefold() in RESERVED:
        raise ValueError("Для настоящих администраторов есть звания Telegram. Роль не даёт прав.")
    return tag
