"""Run KREW with optional automatic, verified updates.

Usage: python launcher.py
AUTO_UPDATE=1 opts in to install published releases automatically.
Keep exactly one launcher per BOT_TOKEN.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from main import BASE, load_dotenv
import updater

LOG = logging.getLogger("krew.launcher")


def stop_child(child: subprocess.Popen, timeout: int = 15) -> None:
    if child.poll() is not None:
        return
    try:
        if os.name == "nt":
            child.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            child.send_signal(signal.SIGINT)
        child.wait(timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def run() -> int:
    load_dotenv(BASE / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if sys.version_info < (3, 11):
        LOG.error("Нужен Python 3.11+")
        return 1
    mode = os.getenv("AUTO_UPDATE", "0") == "1"
    configured = bool(os.getenv("UPDATE_MANIFEST_URL", "").strip())
    if mode and not configured:
        LOG.error("AUTO_UPDATE=1, но UPDATE_MANIFEST_URL отсутствует; автообновление отключено")
        mode = False
    try:
        interval = max(300, int(os.getenv("UPDATE_CHECK_INTERVAL", "3600")))
    except ValueError:
        interval = 3600
    grace = 25  # If the newly updated bot dies quickly, restore previous code.
    LOG.info("Запуск KREW %s | автообновление %s", updater.current_version(BASE), "включено" if mode else "выключено")
    process = None
    next_check = time.monotonic() + 10
    applied = None
    since = time.monotonic()
    failures = 0
    try:
        while True:
            if process is None:
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                process = subprocess.Popen([sys.executable, str(BASE / "main.py")], cwd=BASE, creationflags=creationflags)
                since = time.monotonic()
            rc = process.poll()
            if rc is not None:
                if applied is not None and time.monotonic() - since < grace:
                    LOG.error("Новая версия завершилась сразу (код %s) — возвращаю прежний код", rc)
                    try:
                        updater.restore_journal(applied, BASE)
                        LOG.warning("Откат выполнен. Резервная копия БД сохранена в %s", applied)
                    except (OSError, updater.UpdateError):
                        LOG.exception("Автоматический откат не удался: нужна ручная проверка")
                        return 1
                    applied = None
                    # Don't automatically retry a broken release on every restart.
                    next_check = time.monotonic() + interval
                    failures = 0
                else:
                    LOG.error("Бот завершился с кодом %s", rc)
                    failures += 1
                    if failures >= 3 and time.monotonic() - since < 15:
                        LOG.error("Три быстрых аварийных запуска. Проверь BOT_TOKEN и журнал ошибок.")
                        return 1
                    if time.monotonic() - since > 60:
                        failures = 0
                    time.sleep(min(failures * 3, 15))
                process = None
                continue
            if applied is not None and time.monotonic() - since >= grace:
                LOG.info("Проверка запуска пройдена после обновления; установлена KREW %s", updater.current_version(BASE))
                applied = None
                failures = 0
            if mode and applied is None and time.monotonic() >= next_check:
                next_check = time.monotonic() + interval
                try:
                    manifest = updater.check_update(BASE)
                    if manifest is not None:
                        LOG.info("Найден официальный релиз KREW %s, проверяю архив", manifest["version"])
                        stage, names = updater.prepare_update(manifest, BASE)
                        try:
                            stop_child(process)
                            process = None
                            applied = updater.install_prepared(stage, names, BASE)
                        finally:
                            import shutil
                            shutil.rmtree(stage.parent, ignore_errors=True)
                        LOG.info("Обновление установлено. Перезапускаю бота.")
                        failures = 0
                except (OSError, updater.UpdateError) as exc:
                    LOG.error("Обновление пропущено: %s. Текущая версия продолжает работать.", exc)
                    if process is None:
                        process = None  # start previous code on next loop
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Остановка KREW")
        return 0
    finally:
        if process is not None:
            stop_child(process)


if __name__ == "__main__":
    raise SystemExit(run())
