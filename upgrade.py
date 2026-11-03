"""Safe data migration from an existing KREW folder: python upgrade.py PATH_TO_OLD_FOLDER."""
from __future__ import annotations
import shutil
import sqlite3
import sys
from pathlib import Path

NEW = Path(__file__).resolve().parent


def upgrade(old: Path) -> list[str]:
    old = old.expanduser().resolve()
    if not old.is_dir() or old == NEW:
        raise ValueError('Укажи путь к ПАПКЕ со старой версией KREW (не текущей).')
    result = []
    source_env = old/'.env'
    target_env = NEW/'.env'
    if source_env.exists():
        if target_env.exists():
            result.append('.env уже существует — не перезаписываем')
        else:
            shutil.copy2(source_env, target_env)
            result.append('Настройки токена (.env) скопированы')
    else:
        result.append('Старый .env не найден; создай вручную из .env.example')
    old_db = old/'data'/'krew.sqlite3'
    new_db = NEW/'data'/'krew.sqlite3'
    if old_db.exists():
        if new_db.exists():
            result.append('База нового проекта существует — не перезаписываем')
        else:
            new_db.parent.mkdir(exist_ok=True)
            with sqlite3.connect(f'file:{old_db.as_posix()}?mode=ro', uri=True) as source:
                with sqlite3.connect(new_db) as destination:
                    source.backup(destination)
                    if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('База не прошла проверку целостности')
            result.append('База SQLite безопасно скопирована (XP, настройки, монеты, предупреждения)')
    else:
        result.append('Старой базы нет — KREW запустится с чистой базой')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Пример: python upgrade.py "C:\\Users\\User\\Desktop\\KREW_Bot_0.1.0"')
        raise SystemExit(2)
    try:
        for item in upgrade(Path(sys.argv[1])):
            print('✅', item)
        print('Далее: python main.py')
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print('❌ Ошибка переноса:', exc)
        raise SystemExit(1)
