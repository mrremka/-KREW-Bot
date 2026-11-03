"""Create an integrity-checked SQLite backup. Usage: python backup.py"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
BASE = Path(__file__).resolve().parent

def backup(source: Path | None = None, destination: Path | None = None) -> Path:
    source = source or BASE / "data" / "krew.sqlite3"
    if not source.is_file():
        raise FileNotFoundError("База не найдена. Сначала запусти бота.")
    folder = BASE / "backups"
    folder.mkdir(exist_ok=True)
    destination = destination or folder / ("krew_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".sqlite3")
    if destination.exists():
        raise FileExistsError(destination)
    with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Проверка целостности не пройдена")
    return destination

if __name__ == "__main__":
    try:
        print("✅ Резервная копия:", backup())
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print("❌ Ошибка:", exc)
        raise SystemExit(1)
