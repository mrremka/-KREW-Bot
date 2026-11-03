"""KREW Telegram group bot. Start: python main.py"""
from __future__ import annotations
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from krew.api import TelegramAPI, TelegramError
from krew.core import BotCore
from krew.db import Database
from krew.web import start_server
from krew.news import NewsBroadcaster

BASE = Path(__file__).resolve().parent


def load_dotenv(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.isidentifier() and key not in os.environ:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[key] = value


def init_logging():
    logs = BASE / "logs"
    logs.mkdir(exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file = RotatingFileHandler(logs / "krew.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(formatter)
    logger.addHandler(stream)
    logger.addHandler(file)


def run():
    load_dotenv(BASE / ".env")
    init_logging()
    logger = logging.getLogger("krew")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("❌ В файле .env не указан BOT_TOKEN. Скопируй .env.example → .env и добавь токен.")
        return 1
    api = TelegramAPI(token)
    db = Database(BASE / "data" / "krew.sqlite3")
    web_server = None
    try:
        me = api.call("getMe")
        username = me.get("username", "")
        logger.info("KREW запущен: @%s", username)
        if os.getenv("ENABLE_WEB", "1") == "1":
            try:
                web_server = start_server(token, BASE / "data" / "krew.sqlite3",
                    os.getenv("WEB_HOST", "127.0.0.1"), int(os.getenv("WEB_PORT", "8090")), api)
                logger.info("Mini App web server started on %s:%s", *web_server.server_address)
            except (OSError, ValueError):
                logger.exception("Не удалось запустить веб-панель. Бот продолжит работать")
        # Telegram command menu. Non-fatal if insufficient permissions or API failure.
        try:
            api.call("setMyCommands", commands=[
                {"command":"help", "description":"Справка по KREW"},
                {"command":"panel", "description":"Панель управления Mini App"},
                {"command":"digest", "description":"Сводка активности за неделю (админ)"},
                {"command":"setup", "description":"Панель настроек администратора"},
                {"command":"diagnostics", "description":"Проверка прав бота (админ)"},
                {"command":"rules", "description":"Правила группы"},
                {"command":"report", "description":"Пожаловаться на сообщение (ответом)"},
                {"command":"reports", "description":"Просмотр жалоб (админ)"},
                {"command":"myreports", "description":"Мои жалобы и решения (в личке)"},
                {"command":"notify", "description":"Управление уведомлениями (ЛС)"},
                {"command":"news", "description":"Новости обновлений: /news on|off"},
                {"command":"stats", "description":"Статистика группы (админ)"},
                {"command":"profile", "description":"Мой профиль и уровень"},
                {"command":"top", "description":"Рейтинг активности"},
                {"command":"daily", "description":"Ежедневная награда"},
                {"command":"mission", "description":"Ежедневное задание"},
                {"command":"claim", "description":"Забрать награду за задание"},
                {"command":"thanks", "description":"Поблагодарить участника (ответом)"},
                {"command":"quiz", "description":"Викторина"},
                {"command":"rps", "description":"Камень · Ножницы · Бумага"},
                {"command":"shop", "description":"Магазин значков"},
            ])
        except TelegramError:
            logger.warning("Не получилось обновить меню команд, бот продолжит работу")
        webapp_url = os.getenv("WEBAPP_URL", "").strip()
        if webapp_url.startswith("https://"):
            try:
                api.call("setChatMenuButton", menu_button={"type":"web_app", "text":"KREW Panel", "web_app":{"url":webapp_url}})
            except TelegramError:
                logger.warning("Не удалось настроить кнопку Mini App в меню")
        # Polling and webhook must not operate simultaneously.
        api.call("deleteWebhook", drop_pending_updates=False)
        core = BotCore(api, db, username)
        broadcaster = NewsBroadcaster(api, db, BASE)
        if os.getenv("ANNOUNCE_UPDATES", "0") == "1":
            try:
                broadcaster.stage_current_release()
            except (OSError, ValueError) as exc:
                logger.error("Новости релиза отключены: %s", exc)
        offset = None
        backoff = 2
        while True:
            try:
                params = {"timeout": 2 if broadcaster.enabled and db.has_news_work() else 25,
                          "allowed_updates": ["message", "edited_message", "callback_query"]}
                if offset is not None:
                    params["offset"] = offset
                updates = api.call("getUpdates", **params)
                backoff = 2
                for update in updates:
                    try:
                        core.handle(update)
                    except Exception:
                        logger.exception("Ошибка обработки Telegram-обновления %s", update.get("update_id"))
                    offset = update["update_id"] + 1
                core.maintenance()
                broadcaster.tick()
            except TelegramError as exc:
                if exc.status_code == 409:
                    logger.error("Конфликт: бот уже запущен в другом месте. Останови второй процесс.")
                else:
                    logger.warning("Telegram недоступен: %s", exc.description)
                delay = min(max(exc.retry_after, backoff), 45)
                time.sleep(delay)
                backoff = min(backoff * 2, 45)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
        return 0
    except TelegramError as exc:
        logger.error("Не удалось подключить бота: %s", exc.description)
        return 1
    finally:
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())
