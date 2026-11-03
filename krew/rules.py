"""Pure moderation rules, independent of Telegram and databases."""
from __future__ import annotations
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass

LINK = re.compile(r"(?i)(?:https?://[^\s<>]+|www\.[^\s<>]+|t\.me/[^\s<>]+|telegram\.me/[^\s<>]+|(?<![\w@])(?:[a-z0-9-]+\.)+[a-z]{2,24}(?:/[^\s<>]*)?)")


def has_link(text: str, entities: list[dict] | None = None) -> bool:
    if entities and any(e.get("type") in {"url", "text_link"} for e in entities):
        return True
    return bool(LINK.search(text or ""))


def contains_blocked_word(text: str, words: list[str]) -> str | None:
    text = (text or "").casefold()
    for raw in words:
        word = raw.casefold().strip()
        if word and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text):
            return raw
    return None


def clean_word(word: str) -> str:
    value = " ".join(word.casefold().split())
    if not 2 <= len(value) <= 48 or "\n" in word:
        raise ValueError("Слово/фраза должна содержать 2–48 символов")
    return value


@dataclass
class FloodGuard:
    limit: int = 6
    window: float = 8.0

    def __post_init__(self) -> None:
        self._times = defaultdict(deque)
        self._repeats = defaultdict(deque)
        self._last_cleanup = 0.0

    def check(self, chat_id: int, user_id: int, text: str, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        key = (chat_id, user_id)
        times = self._times[key]
        while times and times[0] <= now - self.window:
            times.popleft()
        times.append(now)
        norm = " ".join((text or "").casefold().split())[:500]
        repeated = self._repeats[key]
        while repeated and repeated[0][0] <= now - 35:
            repeated.popleft()
        if norm and len(norm) >= 3:
            repeated.append((now, norm))
        if len(times) > self.limit:
            times.clear()
            return "Слишком много сообщений подряд"
        if norm and sum(value == norm for _, value in repeated) >= 3:
            repeated.clear()
            return "Повторяющиеся сообщения"
        if now - self._last_cleanup > 300:
            self.cleanup(now)
            self._last_cleanup = now
        return None

    def cleanup(self, now: float) -> None:
        for cache, duration in ((self._times, self.window), (self._repeats, 35)):
            for key, values in list(cache.items()):
                while values and (values[0] if cache is self._times else values[0][0]) <= now - duration:
                    values.popleft()
                if not values:
                    del cache[key]

# A whitelist is an exception to a link ban, never a replacement for the ban.
from urllib.parse import urlsplit


def normalize_domain(text: str) -> str:
    """Accept a domain (not a URL/path/IP); return canonical ASCII domain."""
    value = text.strip().lower().rstrip('.')
    if value.startswith('www.'):
        value = value[4:]
    if '/' in value or '@' in value or ':' in value or len(value) > 253:
        raise ValueError('Укажи домен без https://, например example.org')
    try:
        value = value.encode('idna').decode('ascii')
    except (UnicodeError, ValueError):
        raise ValueError('Некорректный домен') from None
    if len(value.split('.')) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.')):
        raise ValueError('Некорректный домен')
    if not re.search(r'[a-z]', value.rsplit('.', 1)[-1]):
        raise ValueError('Некорректный домен')
    return value


def link_domains(text: str, entities: list[dict] | None = None) -> tuple[bool, list[str]]:
    """Returns (detected_any, domains). Unknown entity links are conservatively denied."""
    urls = [match.group(0).rstrip('.,!?:;)]}') for match in LINK.finditer(text or '')]
    entity_links = [e for e in (entities or []) if e.get('type') in {'url', 'text_link'}]
    urls.extend(e['url'] for e in entity_links if e.get('type') == 'text_link' and e.get('url'))
    domains: list[str] = []
    for url in urls:
        try:
            host = urlsplit(url if '://' in url else 'https://' + url).hostname or ''
            domains.append(normalize_domain(host))
        except (ValueError, TypeError):
            domains.append('')
    if entity_links and not urls:
        domains.append('')
    return bool(urls or entity_links), domains


def disallowed_link(text: str, entities: list[dict] | None, allowed: list[str]) -> bool:
    found, domains = link_domains(text, entities)
    if not found:
        return False
    return not domains or any(
        not domain or not any(domain == a or domain.endswith('.' + a) for a in allowed)
        for domain in domains
    )


def excessive_mentions(text: str, entities: list[dict] | None, limit: int = 5) -> bool:
    """Detect mass @mentions without treating email addresses as mentions."""
    if not text or not 3 <= limit <= 15:
        return False
    entities = entities or []
    from_entities = sum(1 for e in entities if e.get("type") in ("mention", "text_mention"))
    # Telegram supplies entities for real mentions. Regex is a fallback for mock clients.
    from_text = len(re.findall(r"(?<![\w@])@[a-zA-Z0-9_]{5,32}\b", text))
    return max(from_entities, from_text) >= limit

def excessive_caps(text: str) -> bool:
    """Reject long uppercase shouting, not acronyms or short expressions."""
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 24:
        return False
    uppers = sum(c.isupper() for c in letters)
    return uppers >= 18 and uppers / len(letters) >= .80
