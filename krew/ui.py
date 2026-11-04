"""KREW's calm, compact Telegram UI. No third-party dependencies.

Text commands use HTML; informational reports may use Bot API rich messages
(tables, headings), with a standard-message fallback for compatibility.
"""
from __future__ import annotations
import html

SECTIONS = {
    'home': ('Главная', ()),
    'start': ('Начало', (
        ('/help', 'Открыть это меню'),
        ('/rules', 'Правила группы'),
        ('/profile', 'Профиль и опыт'),
        ('/whois', 'Карточка участника'),
        ('/myrole', 'Моя роль в чате'),
        ('/roles', 'Роли участников'),
        ('/top', 'Рейтинг участников'),
        ('/version', 'Версия бота'),
        ('/ping', 'Проверка в личке'),
    )),
    'games': ('Игры и награды', (
        ('/daily', 'Ежедневная награда'),
        ('/mission', 'Задание на сегодня'),
        ('/claim', 'Получить награду'),
        ('/quiz', 'Викторина'),
        ('/rps', 'Камень, ножницы, бумага'),
        ('/duel', 'Дуэль ответом'),
        ('/shop', 'Игровой магазин'),
        ('/thanks', 'Поблагодарить участника'),
    )),
    'shield': ('Защита чата', (
        ('/setup', 'Настройки защиты'),
        ('/shield', 'Текущие фильтры'),
        ('/badword', 'Стоп-слова'),
        ('/allowlink', 'Исключения для ссылок'),
        ('/raid', 'Защита при рейде'),
        ('/diagnostics', 'Проверка прав бота'),
    )),
    'moderation': ('Модерация', (
        ('/warn', 'Предупредить ответом'),
        ('/mute 10m', 'Ограничить ответом'),
        ('/ban', 'Заблокировать ответом'),
        ('/pin', 'Закрепить ответом'),
        ('/unpin', 'Открепить сообщение'),
        ('/reports', 'Жалобы'),
        ('/modlog', 'Журнал действий'),
        ('/modcenter', 'Центр модерации'),
        ('/role VIP', 'Назначить тег участнику'),
        ('/unrole', 'Снять тег участника'),
        ('/admintitle', 'Звание администратора'),
    )),
    'analytics': ('Статистика', (
        ('/stats', 'Статистика группы'),
        ('/digest', 'Сводка за неделю'),
        ('/status', 'Состояние бота'),
        ('/top', 'Рейтинг активности'),
    )),
    'personal': ('Личное', (
        ('/panel', 'Открыть Mini App'),
        ('/myreports', 'История моих жалоб'),
        ('/notify on', 'Уведомления о жалобах'),
        ('/notify off', 'Отключить уведомления'),
        ('/news on', 'Новости версий'),
        ('/news off', 'Отключить новости'),
        ('/privacy', 'Приватность'),
        ('/voicehelp', 'О голосовых'),
        ('/transcribe', 'Распознать свой войс'),
    )),
}

LABELS = (
    ('start', '🧭 Начало'), ('games', '🎮 Игры'),
    ('shield', '🛡 Защита'), ('moderation', '🔨 Модерация'),
    ('analytics', '📊 Статистика'), ('personal', '👤 Личное'),
)


def keyboard(page: str, *, private: bool = False, panel_url: str = '') -> dict:
    if page == 'home':
        buttons = [dict(text=label, callback_data=f'help:{key}') for key,label in LABELS]
        rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        if private and panel_url.startswith('https://'):
            rows.append([{'text':'◈ Открыть Mini App', 'web_app':{'url':panel_url}}])
    else:
        rows = [[{'text':'‹ Разделы', 'callback_data':'help:home'},
                 {'text':'✕ Закрыть', 'callback_data':'help:close'}]]
    return {'inline_keyboard': rows}


def help_page(page: str) -> tuple[str, str]:
    """(regular HTML, rich HTML) — both contain equivalent information."""
    if page not in SECTIONS:
        raise ValueError('Unknown help page')
    if page == 'home':
        plain = ('✦ <b>KREW</b> · Команды и возможности\n'
                 '<i>Порядок в чате, развлечения и удобное управление.</i>\n\n'
                 'Выбери раздел ниже — покажу только нужные команды.\n'
                 '<i>Больше не нужно листать огромную справку.</i>')
        rich = ('<h3>✦ KREW</h3><p>Порядок в чате, развлечения и управление.</p>'
                '<p>Выбери интересующий раздел ниже.</p>')
        return plain, rich
    title, cmds = SECTIONS[page]
    regular = (f'<b>✦ KREW · {html.escape(title)}</b>\n\n'
               + '\n'.join(f'<code>{html.escape(command)}</code> — {html.escape(description)}'
                             for command,description in cmds))
    rich_rows = ''.join('<tr><td><code>'+html.escape(command)+'</code></td><td>'
                        +html.escape(description)+'</td></tr>' for command,description in cmds)
    rich = f'<h3>✦ KREW · {html.escape(title)}</h3><table striped compact>{rich_rows}</table>'
    if page in ('moderation','shield','analytics'):
        regular += '\n\n<i>Команды модерации доступны только администраторам.</i>'
        rich += '<p><i>Доступно администраторам группы.</i></p>'
    return regular, rich


def report(title: str, rows: list[tuple[str, str]], note: str = '') -> tuple[str, str]:
    """Compact two-column table + semantically equivalent plain text."""
    title = html.escape(str(title), quote=False)
    plain_rows = ['<b>'+html.escape(str(label),quote=False)+'</b>: '
                  +html.escape(str(value),quote=False) for label,value in rows]
    plain = f'<b>{title}</b>\n\n' + '\n'.join(plain_rows)
    rich_rows = ''.join('<tr><td>'+html.escape(str(label),quote=False)+'</td><td><b>'
                        +html.escape(str(value),quote=False)+'</b></td></tr>' for label,value in rows)
    rich = f'<h3>{title}</h3><table striped compact>{rich_rows}</table>'
    if note:
        escaped_note = html.escape(str(note),quote=False)
        plain += f'\n\n<i>{escaped_note}</i>'
        rich += f'<p><i>{escaped_note}</i></p>'
    return plain, rich
