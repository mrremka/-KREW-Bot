"""Offline preflight for KREW. Usage: python release_check.py"""
from __future__ import annotations
import os
import sqlite3
import sys
from pathlib import Path
from main import BASE, load_dotenv


def check() -> int:
    load_dotenv(BASE/'.env')
    issues: list[str]=[]
    notes: list[str]=[]
    if sys.version_info < (3,11):
        issues.append('Требуется Python 3.11 или новее.')
    token=os.getenv('BOT_TOKEN','').strip()
    if not token or ':' not in token or token.startswith('PASTE_'):
        issues.append('Укажи действительный BOT_TOKEN в .env (значение не печатается).')
    else:
        notes.append('Токен задан. Он не проверен онлайн — проверь подключение к Telegram.')
    if not (BASE/'krew/static/index.html').is_file() or not (BASE/'krew/static/app.js').is_file():
        issues.append('Файлы Mini App отсутствуют.')
    web_enabled=os.getenv('ENABLE_WEB','1')=='1'
    url=os.getenv('WEBAPP_URL','').strip()
    if web_enabled and url and not url.startswith('https://'):
        issues.append('WEBAPP_URL должен начинаться с https://')
    if web_enabled and not url:
        notes.append('WEBAPP_URL не указан: Mini App будет доступна только в локальном превью.')
    if web_enabled and os.getenv('WEB_HOST','127.0.0.1')=='0.0.0.0':
        notes.append('WEB_HOST=0.0.0.0: не выставляй HTTP-порт в интернет без HTTPS-прокси.')
    dbpath=BASE/'data/krew.sqlite3'
    if dbpath.exists():
        try:
            with sqlite3.connect(f'file:{dbpath.resolve().as_posix()}?mode=ro',uri=True,timeout=5) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    issues.append('База не прошла проверку SQLite.')
                else:
                    notes.append('База SQLite читается и прошла quick_check.')
        except sqlite3.Error:
            issues.append('Не удалось открыть базу SQLite.')
    else:
        notes.append('Базы пока нет: она будет создана при первом запуске.')
    if issues:
        print('❌ Предрелизная проверка не пройдена:')
        for item in issues: print(' -',item)
    else:
        print('✅ Локальная предрелизная проверка пройдена.')
    for item in notes: print('ℹ️',item)
    print('Важно: этот скрипт НЕ заменяет тест живого Telegram-бота, HTTPS и нагрузки.')
    return 1 if issues else 0

if __name__=='__main__':
    raise SystemExit(check())
