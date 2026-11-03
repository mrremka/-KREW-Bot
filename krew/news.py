"""Optional one-to-one announcements to opt-in Telegram bot subscribers."""
from __future__ import annotations
import html
import json
import logging
import os
from pathlib import Path
from .api import TelegramError

LOG = logging.getLogger('krew.news')


def parse_release_notes(base: Path) -> tuple[str, str]:
    data = json.loads((base / 'release_notes.json').read_text(encoding='utf-8'))
    version = (base / 'VERSION').read_text(encoding='utf-8').strip()
    if data.get('version') != version or not isinstance(data.get('title'), str):
        raise ValueError('Версия release_notes.json не соответствует VERSION')
    title = data['title'].strip()
    changes = data.get('changes')
    if not title or len(title) > 120 or not isinstance(changes, list) or not 1 <= len(changes) <= 10:
        raise ValueError('Некорректные заметки релиза')
    if any(not isinstance(c, str) or not 1 <= len(c) <= 230 for c in changes):
        raise ValueError('Некорректный список изменений')
    content = '\n'.join('• ' + html.escape(change) for change in changes)
    # Never send a url supplied by an unknown external manifest.
    content = (f'🚀 <b>{html.escape(title)}</b>\n'
               f'Версия: <code>{html.escape(version)}</code>\n\n{content}\n\n'
               'Спасибо, что используешь KREW!\n'
               'Управлять новостями: /news off')
    if len(content) > 3900:
        raise ValueError('Слишком длинная рассылка')
    return version, content


class NewsBroadcaster:
    def __init__(self, api, db, base: Path):
        self.api = api
        self.db = db
        self.base = base
        self.enabled = os.getenv('ANNOUNCE_UPDATES', '0') == '1'

    def stage_current_release(self) -> int:
        if not self.enabled:
            return 0
        version, message = parse_release_notes(self.base)
        count = self.db.stage_news_release(version, message)
        LOG.info('Новости релиза %s поставлены в очередь: %s подписчиков', version, count)
        return count

    def tick(self) -> str:
        if not self.enabled:
            return 'disabled'
        item = self.db.claim_news_delivery()
        if not item:
            return 'idle'
        try:
            self.api.call('sendMessage', chat_id=item['user_id'], text=item['text'],
                          parse_mode='HTML', link_preview_options={'is_disabled': True})
        except TelegramError as exc:
            if exc.status_code == 429 and exc.retry_after and item['attempts'] < 5:
                self.db.finish_news_delivery(item['version'], item['user_id'], 'pending',
                                             retry_after=exc.retry_after + 3)
                return 'rate_limited'
            # Timeout / ambiguous failure might have sent the message: never automatically
            # retry an unknown outcome, to avoid spam or duplicate messages.
            status = 'failed' if exc.status_code in (400, 403) else 'uncertain'
            self.db.finish_news_delivery(item['version'], item['user_id'], status)
            if exc.status_code == 403:
                self.db.set_news_enabled(item['user_id'], False)
            LOG.warning('Новость %s для подписчика %s: %s', item['version'], item['user_id'], status)
            return status
        self.db.finish_news_delivery(item['version'], item['user_id'], 'sent')
        return 'sent'
