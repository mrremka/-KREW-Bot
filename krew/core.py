"""Core bot: admin controls, protection, community profile and fair games."""
from __future__ import annotations
import html
import os
from pathlib import Path
from collections import defaultdict, deque
import logging
import random
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from krew.db import Database
from krew.api import TelegramError
from krew.rules import FloodGuard, clean_word, contains_blocked_word, disallowed_link, normalize_domain, excessive_mentions, excessive_caps

LOGGER = logging.getLogger("krew")

QUOTES = (
    "Сегодня хороший день, чтобы написать что-то полезное в чат.",
    "Если идея кажется сложной — начни с маленькой версии.",
    "Лучший мем ещё не отправлен.",
    "Кто-то в этом чате точно знает ответ, но пока молчит.",
    "Ставлю на неожиданную развязку.",
    "Спросите ещё раз после чашки чая.",
    "Определённо да.", "Скорее всего нет.", "Прогноз пока туманный.",
)
QUIZZES = [
    ("Какая планета ближе всего к Солнцу?", ["Венера", "Меркурий", "Марс", "Земля"], 1),
    ("Сколько бит в одном байте?", ["4", "8", "16", "32"], 1),
    ("Кто написал «Капитанскую дочку»?", ["Пушкин", "Гоголь", "Толстой", "Чехов"], 0),
    ("Какой океан самый большой?", ["Атлантический", "Индийский", "Тихий", "Северный Ледовитый"], 2),
    ("Чему равно 7 × 8?", ["54", "56", "64", "58"], 1),
    ("Какой язык используют для скриптов в Roblox?", ["C#", "Python", "Luau", "Java"], 2),
    ("В какой игре есть криперы?", ["Terraria", "Minecraft", "Rust", "Factorio"], 1),
    ("Какой химический символ у золота?", ["Ag", "Fe", "Au", "Pb"], 2),
    ("Как называют память, содержимое которой обычно теряется при выключении ПК?", ["SSD", "RAM", "ROM", "HDD"], 1),
    ("Сколько минут в двух часах?", ["60", "90", "100", "120"], 3),
    ("Какова основная единица силы тока в СИ?", ["Вольт", "Ампер", "Ом", "Ватт"], 1),
    ("Сколько граней у обычного кубика?", ["4", "6", "8", "10"], 1),
]
BADGES = {"spark": ("✨ Искра", 40), "heart": ("💜 Сердце", 100), "star": ("⭐ Звезда", 220), "crown": ("👑 Корона", 500)}
LABELS = {"antispam": "Антиспам", "antilinks": "Защита от ссылок", "antiforward": "Запрет пересылок", "antiraid": "Авто-анти-рейд", "captcha": "Проверка новичков", "welcome": "Приветствия", "fun": "Развлечения", "levels": "Уровни", "antimentions": "Массовые упоминания", "anticaps": "CAPS-спам"}
ADMIN_COMMANDS = {"status", "pin", "unpin", "setup", "warn", "warnings", "unwarn", "mute", "unmute", "ban", "kick", "unban", "badword", "setrules", "modlog", "warnlimit", "welcometext", "allowlink", "raid", "reports", "stats", "diagnostics", "panel", "digest", "shield", "mentionlimit"}
FUN_COMMANDS = {"daily", "roll", "coin", "eightball", "duel", "quiz", "fortune", "shop", "buy", "rps", "achievements", "mission", "claim", "thanks"}
COMMAND_PATTERN = re.compile(r"^/([\w]+)(?:@([\w]+))?(?:\s+([\s\S]*))?$", re.UNICODE)

def installed_version() -> str:
    """Read installed version at call time, including after updates."""
    try:
        return (Path(__file__).resolve().parents[1] / 'VERSION').read_text(encoding='utf-8').strip() or 'unknown'
    except OSError:
        return 'unknown'


def runtime_status() -> str:
    """Public, non-secret status summary; never show tokens or local paths."""
    version = esc(installed_version())
    panel = '✅ Подключена' if os.getenv('ENABLE_WEB', '1') == '1' and os.getenv('WEBAPP_URL', '').startswith('https://') else '⏸ Не подключена к Telegram'
    return f'🟢 <b>KREW работает</b>\n🏷 Версия: <code>{version}</code>\n📲 Mini App: {panel}'


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)

def mention(user: dict) -> str:
    name = user.get("first_name") or user.get("username") or "Участник"
    return f'<a href="tg://user?id={int(user["id"])}">{esc(name)}</a>'

def human_name(user: dict) -> str:
    return " ".join(filter(None, [user.get("first_name", ""), user.get("last_name", "")])).strip() or user.get("username") or "Участник"

def level(xp: int) -> int:
    return 1 + int((max(0, xp) / 60) ** .5)

def parse_duration(arg: str) -> tuple[int, str]:
    parts = (arg or "").strip().split(maxsplit=1)
    matched = re.fullmatch(r"(\d{1,4})([mhd])", parts[0].lower()) if parts else None
    if not matched:
        raise ValueError("Формат: /mute 10m причина (m — минуты, h — часы, d — дни)")
    amount, unit = int(matched.group(1)), matched.group(2)
    seconds = amount * {"m": 60, "h": 3600, "d": 86400}[unit]
    if seconds < 30 or seconds > 365 * 86400:
        raise ValueError("Мут должен длиться от 1 минуты до 365 дней")
    return seconds, (parts[1] if len(parts) > 1 else "Без причины")[:160]

class BotCore:
    def __init__(self, api, db: Database, username: str = ""):
        self.api = api
        self.db = db
        self.username = username.lower().lstrip('@')
        self.flood = FloodGuard()
        self._admin_cache: dict[tuple[int, int], tuple[bool, float]] = {}
        self._cooldowns: dict[tuple[int, int, str], float] = {}
        self._words_cache: dict[int, tuple[list[str], float]] = {}
        self._joins: dict[int, deque] = defaultdict(deque)
        self._last_maintenance = 0.0

    def call(self, method: str, **data):
        return self.api.call(method, **data)

    def send(self, chat_id: int, text: str, **options):
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                         link_preview_options={"is_disabled": True}, **options)

    def is_admin(self, chat_id: int, user_id: int, fresh: bool = False) -> bool:
        key = (chat_id, user_id)
        now = time.monotonic()
        if not fresh and key in self._admin_cache and self._admin_cache[key][1] > now:
            return self._admin_cache[key][0]
        try:
            result = self.call("getChatMember", chat_id=chat_id, user_id=user_id)
            admin = result.get("status") in {"creator", "administrator"}
        except TelegramError:
            admin = False
        self._admin_cache[key] = (admin, now + 45)
        return admin

    def settings_text(self, chat_id: int) -> str:
        cfg = self.db.get_chat(chat_id)
        rows = [f"• {label}: {'✅ ВКЛ' if cfg[field] else '⏸ ВЫКЛ'}" for field, label in LABELS.items()]
        return ("<b>⚙️ KREW — настройки чата</b>\n\n" + "\n".join(rows) +
                "\n\nАнтиспам: более 6 сообщений за 8 секунд или 3 повтора."
                f"\nАвтомут после {cfg['warn_limit']} предупреждений."
                f"\nЛимит упоминаний: {cfg['mention_limit']} на сообщение."
                "\nАвтозащита от рейда: 5 вступлений за 60 секунд → 15 минут проверки новичков."
                "\nКапча: 5 минут на ответ; после истечения — исключение."
                "\n\nПравила: /setrules · Фильтр: /badword"
                "\nИсключения для ссылок: /allowlink · Рейд: /raid"
                "\nПорог предупреждений: /warnlimit 3 · /mentionlimit 5")

    def settings_keyboard(self, chat_id: int) -> dict:
        cfg = self.db.get_chat(chat_id)
        return {"inline_keyboard": [[{"text": f"{'🟢' if cfg[field] else '⚪'} {label}", "callback_data": f"cfg:{field}"}]
                                     for field, label in LABELS.items()]}

    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            self.on_callback(update["callback_query"])
        elif "message" in update:
            self.on_message(update["message"])
        elif "edited_message" in update:
            self.on_edited_message(update["edited_message"])

    def on_callback(self, callback: dict) -> None:
        data = callback.get("data", "")
        from_user = callback.get("from") or {}
        msg = callback.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        answer = "Кнопка больше недоступна"
        try:
            if data.startswith("cfg:") and chat_id and chat.get("type") in ("group", "supergroup"):
                if not self.is_admin(chat_id, from_user.get("id", 0), fresh=True):
                    answer = "Только для администраторов"
                else:
                    field = data.partition(":")[2]
                    if field in LABELS:
                        self.db.toggle(chat_id, field, int(from_user["id"]))
                        self.call("editMessageText", chat_id=chat_id, message_id=msg["message_id"],
                                  text=self.settings_text(chat_id), parse_mode="HTML", reply_markup=self.settings_keyboard(chat_id))
                        answer = "Настройка изменена"
            elif data.startswith("v:") and chat_id and chat.get("type") in ("group", "supergroup"):
                _, uid, choice = data.split(":")
                if int(uid) != int(from_user.get("id", 0)):
                    answer = "Это проверка другого участника"
                else:
                    answer = self.verify_newcomer(chat_id, int(uid), int(choice), msg)
            elif data.startswith("rep:") and chat_id and chat.get("type") == "private":
                # Private DM callback carries target GROUP ID; membership checked fresh.
                _, group_s, report_s, action = data.split(":", 3)
                answer = self.resolve_report_callback(int(group_s), from_user, int(report_s), action, msg)
            elif data.startswith("rps:") and chat_id and chat.get("type") in ("group", "supergroup"):
                _, game_s, choice_s = data.split(":")
                result = self.db.play_rps(int(game_s), chat_id, int(from_user["id"]), int(choice_s))
                answer = {"win": "🏆 Победа! +8 монет", "lose": "Поражение. Реванш?", "draw": "Ничья!", "already": "Партия уже сыграна", "expired": "Время вышло", "not_yours": "Это игра другого участника", "invalid": "Неверный ход"}[result]
                if result in {"win", "lose", "draw"}:
                    self.call("editMessageText", chat_id=chat_id, message_id=msg["message_id"],
                              text=f"🎮 Камень · Ножницы · Бумага\n{esc(answer)}", parse_mode="HTML")
            elif data.startswith("q:") and chat_id and chat.get("type") in ("group", "supergroup"):
                _, quiz_s, choice_s = data.split(":", 2)
                result = self.db.answer_quiz(int(quiz_s), chat_id, int(from_user["id"]), int(choice_s))
                answer = {"correct":"✅ Верно! +15 монет", "wrong":"❌ Не угадал. Попробуй следующий вопрос.",
                          "already":"Ты уже ответил на этот вопрос", "expired":"Время вышло", "not_found":"Викторина не найдена"}[result]
            self.call("answerCallbackQuery", callback_query_id=callback["id"], text=answer, show_alert=False)
        except (ValueError, KeyError, TelegramError):
            LOGGER.warning("Не удалось обработать кнопку")
            try:
                self.call("answerCallbackQuery", callback_query_id=callback["id"], text="Не удалось выполнить действие")
            except TelegramError:
                pass

    def on_message(self, msg: dict) -> None:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        kind = chat.get("type", "private")
        user = msg.get("from") or {}
        text = msg.get("text") or ""
        command = COMMAND_PATTERN.match(text.strip())
        cmd = command.group(1).lower() if command else ""
        args = (command.group(3) or "").strip() if command else ""
        if command and command.group(2) and command.group(2).lower() != self.username:
            return
        if kind == "private":
            uid=int(user.get("id") or 0)
            if cmd in {"status", "version"}:
                self.send(chat_id, runtime_status())
                return
            if cmd == "ping":
                self.send(chat_id, f"🏓 Pong! KREW <code>{esc(installed_version())}</code> работает.")
                return
            if cmd == "start" and uid:
                self.db.register_private(uid)
            if cmd == "news" and uid:
                if args not in ("on", "off"):
                    state = "включена" if self.db.news_enabled(uid) else "выключена"
                    self.send(chat_id, f"📣 Рассылка новостей KREW: {state}.\nПодписка: /news on\nОтписка: /news off")
                elif not self.db.set_news_enabled(uid, args == "on"):
                    self.send(chat_id, "Сначала отправь /start, затем /news on.")
                else:
                    self.send(chat_id, "📣 Новости KREW " + ("включены. Буду писать о новых версиях." if args == "on" else "отключены. Рассылки больше не будет."))
            elif cmd == "notify" and uid:
                if args not in ("on", "off"):
                    self.send(chat_id, "🔔 Уведомления о жалобах: /notify on или /notify off")
                else:
                    self.db.register_private(uid, enabled=(args=="on"))
                    self.send(chat_id, "🔔 Уведомления " + ("включены" if args=="on" else "отключены") + ".")
            elif cmd == "myreports" and uid:
                entries=self.db.user_reports(uid)
                if not entries:
                    self.send(chat_id,"У тебя пока нет обращений.")
                else:
                    labels={"open":"На рассмотрении","rejected":"Отклонена","warned":"Подтверждена","closed":"Закрыта"}
                    rows=[]
                    for r in entries:
                        reason=("\nПричина: "+esc(r["decision_reason"])) if r["decision_reason"] else ""
                        rows.append(f"#{r['id']} · {esc(r['title'] or r['chat_id'])} · {labels.get(r['status'],r['status'])}{reason}")
                    self.send(chat_id,"📩 <b>Мои обращения</b>\n\n"+"\n\n".join(rows))
            elif cmd == "reject" and uid:
                self.private_reject(chat_id,uid,args)
            elif uid and (msg.get("reply_to_message") or {}).get("text"):
                # Telegram ForceReply for reason; validate the reply marker before use.
                template=(msg["reply_to_message"].get("text") or "")
                match=re.search(r"KREW_REJECT (-\d+) (\d+)$", template.strip())
                if match and text.strip():
                    self.private_reject(chat_id,uid,f"{match[1]} {match[2]} {text.strip()}")
            elif cmd == "start" and args.startswith("reports_"):
                self.private_reports(chat_id, user.get("id", 0), args[len("reports_"):])
            elif cmd == "reports":
                self.private_reports(chat_id, user.get("id", 0), args)
            elif cmd in {"start", "help", "privacy", "panel"}:
                self.private_help(chat_id, cmd)
            return
        if kind not in ("group", "supergroup"):
            return
        cfg = self.db.ensure_chat(chat_id, chat.get("title", ""))
        if msg.get("new_chat_members"):
            self.handle_newcomers(msg, cfg)
            return
        if msg.get("left_chat_member"):
            departed = msg["left_chat_member"]
            if departed.get("id"):
                self.db.delete_challenge(chat_id, int(departed["id"]))
            return
        if not user or user.get("is_bot"):
            return
        if msg.get("sender_chat"):
            return  # Anonymous admin / channel-as-chat: don't punish a synthetic user ID.
        user_id = int(user["id"])
        admin = self.is_admin(chat_id, user_id)
        if not admin and self.moderate(msg, cfg, user):
            return
        if cmd:
            try:
                self.command(msg, cmd, args, user, admin)
            except TelegramError:
                LOGGER.exception("Telegram command failed (%s)", cmd)
                # Don't send a second reply if Telegram is temporarily unavailable.
            except Exception:
                LOGGER.exception("Command bug (%s)", cmd)
                try:
                    self.send(chat_id, "⚠️ Не удалось выполнить команду. Ошибка записана в журнал.")
                except TelegramError:
                    pass
            return
        if msg.get("text") or msg.get("caption"):
            self.db.activity(chat_id, user_id, human_name(user), enabled=bool(cfg["levels"]))

    def on_edited_message(self, msg: dict) -> None:
        """Edits are moderated, but never counted twice or executed as commands."""
        chat = msg.get("chat") or {}
        user = msg.get("from") or {}
        if chat.get("type") not in ("group", "supergroup") or not user.get("id") or user.get("is_bot") or msg.get("sender_chat"):
            return
        if not self.is_admin(chat["id"], user["id"]):
            self.moderate(msg, self.db.ensure_chat(chat["id"], chat.get("title", "")), user, edited=True)

    def private_help(self, chat_id: int, command: str) -> None:
        if command == "panel" or (command == "start" and os.getenv("WEBAPP_URL", "").startswith("https://")):
            url = os.getenv("WEBAPP_URL", "").strip()
            if url.startswith("https://"):
                self.send(chat_id,"🛡 <b>KREW Control Center</b>\nУправляй настройками своих групп в Mini App.",
                    reply_markup={"inline_keyboard":[[{"text":"Открыть панель", "web_app":{"url":url}}]]})
            else:
                self.send(chat_id,"⚙️ Мини-приложение ещё не настроено. В .env укажи WEBAPP_URL=https://ваш-домен.")
            return
        if command == "privacy":
            self.send(chat_id, "🔐 <b>Приватность KREW</b>\nБот хранит ID чатов и пользователей, имена, счётчики активности, монеты, предупреждения, настройки, причины решений по жалобам и ограниченный журнал модерации (30 дней). <b>Содержимое сообщений не сохраняется</b>. Для добровольной рассылки новостей хранится флаг подписки и статус доставки по версии. Сообщения обрабатываются для антиспама и фильтров. Уведомления: /notify on|off и /news on|off.")
            return
        self.send(chat_id, "<b>Привет! Это KREW 1.0 RC.</b> 🛡️🎲\n\nЯ объединяю защиту групповых чатов и развлечения участников.\n\nДобавь меня в группу как администратора с правами удаления и ограничения участников, затем напиши <code>/setup</code>.\n\nКоманды: /help в группе.\nЖалобы: /myreports · Уведомления о жалобах: /notify on|off\nНовости релизов (по желанию): /news on|off\nПриватность: /privacy")

    def words(self, chat_id: int) -> list[str]:
        # Rule edits in the Mini App must take effect on the very next message.
        return self.db.list_words(chat_id)

    def moderate(self, msg: dict, cfg: dict, user: dict, edited: bool = False) -> bool:
        chat_id = msg["chat"]["id"]
        user_id = user["id"]
        body = msg.get("text") or msg.get("caption") or ""
        entity_list = msg.get("entities") or msg.get("caption_entities") or []
        reason = None
        if cfg["antilinks"] and disallowed_link(body, entity_list, self.db.list_domains(chat_id)):
            reason = "Ссылки запрещены в этом чате"
        if not reason and cfg["antiforward"] and (msg.get("forward_origin") or msg.get("forward_from") or msg.get("forward_from_chat")):
            reason = "Пересланные сообщения запрещены"
        if not reason:
            offending = contains_blocked_word(body, self.words(chat_id))
            if offending:
                reason = "Сообщение содержит запрещённое слово"
        if not reason and cfg["antimentions"] and excessive_mentions(body, entity_list, cfg["mention_limit"]):
            reason = "Слишком много упоминаний в одном сообщении"
        if not reason and cfg["anticaps"] and excessive_caps(body):
            reason = "Слишком много текста заглавными буквами"
        if not reason and cfg["antispam"] and not edited:
            reason = self.flood.check(chat_id, user_id, body)
        if not reason:
            return False
        try:
            self.call("deleteMessage", chat_id=chat_id, message_id=msg["message_id"])
        except TelegramError:
            LOGGER.warning("Не удалось удалить сообщение в чате %s — проверьте права", chat_id)
            return True  # no warning if moderation did not actually succeed
        self.issue_warning(chat_id, user, None, reason)
        return True

    def issue_warning(self, chat_id: int, user: dict, admin_id: int | None, reason: str) -> None:
        count = self.db.warn(chat_id, user["id"])
        self.db.log_action(chat_id, admin_id, user["id"], "warn", reason)
        limit = self.db.get_chat(chat_id)["warn_limit"]
        if count >= limit:
            try:
                self.restrict(chat_id, user["id"], seconds=600)
            except TelegramError:
                self.send(chat_id, f"⚠️ {mention(user)}: {count}/{limit} предупреждений. Автомут не сработал — проверьте права бота.")
                return
            self.db.reset_warn(chat_id, user["id"])
            self.db.log_action(chat_id, admin_id, user["id"], "automute", "Порог предупреждений")
            self.send(chat_id, f"🔇 {mention(user)} получил мут на 10 минут. Причина: {esc(reason)}")
        else:
            self.send(chat_id, f"⚠️ {mention(user)} — предупреждение {count}/{limit}.\nПричина: {esc(reason)}")

    def restrict(self, chat_id: int, user_id: int, seconds: int | None) -> None:
        if seconds is None:
            self._restore_permissions(chat_id, user_id)
            return
        self.call("restrictChatMember", chat_id=chat_id, user_id=user_id,
                  permissions={"can_send_messages": False}, until_date=int(time.time()) + seconds)

    def _allow_fun(self, chat_id: int, user_id: int, cmd: str, seconds: int = 12) -> bool:
        key = (chat_id, user_id, cmd)
        now = time.monotonic()
        if self._cooldowns.get(key, 0) > now:
            return False
        self._cooldowns[key] = now + seconds
        if len(self._cooldowns) > 10000:
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > now}
        return True

    def command(self, msg: dict, cmd: str, args: str, user: dict, cached_admin: bool) -> None:
        chat_id, user_id = msg["chat"]["id"], user["id"]
        if cmd == "version":
            self.send(chat_id, f"🏷 <b>KREW</b> · версия <code>{esc(installed_version())}</code>")
            return
        if cmd in {"start", "help"}:
            self.send(chat_id, "<b>🛡️ KREW 1.0 RC — команды</b>\n\n<b>Участникам:</b> /rules /profile /top /daily /mission /claim /thanks /roll /coin /eightball /duel /quiz /rps /fortune /shop /buy /achievements\n<b>Жалобы:</b> /report ответом на сообщение; в личке: /myreports /notify on|off /news on|off\n\n<b>Администраторам:</b> /panel /setup /diagnostics /stats /digest /reports /shield /mentionlimit /raid /warn /warnings /unwarn /mute /unmute /kick /ban /unban /badword /allowlink /setrules /welcometext /warnlimit /modlog /status /pin /unpin\n\nДля наказания отвечай командой на сообщение. Версия: /version")
            return
        if cmd == "rules":
            self.send(chat_id, "📜 <b>Правила чата</b>\n" + esc(self.db.get_chat(chat_id)["rules"]))
            return
        if cmd == "profile":
            target = (msg.get("reply_to_message") or {}).get("from") or user
            p = self.db.profile(chat_id, target["id"], human_name(target))
            warnings = self.db.get_warn(chat_id, target["id"])
            badge = BADGES.get(p["active_badge"], ("Нет", 0))[0]
            self.send(chat_id, f"👤 <b>Профиль</b> — {mention(target)}\n🏅 Уровень: <b>{level(p['xp'])}</b>\n✨ Опыт: {p['xp']}\n💬 Сообщений: {p['messages']}\n🪙 Монеты: {p['coins']}\n🎨 Значок: {badge}\n💜 Благодарности: {p['reputation']}\n⚠️ Предупреждения: {warnings}")
            return
        if cmd == "achievements":
            p = self.db.profile(chat_id, user_id, human_name(user))
            milestones = [(10, "💬 Первые сообщения", p["messages"]), (100, "🔥 Активист", p["messages"]),
                          (500, "🏆 Легенда чата", p["messages"]), (7, "🎁 Неделя подряд", p["daily_streak"])]
            rows = [f"{'✅' if progress >= target else '🔒'} {name}: {progress}/{target}" for target, name, progress in milestones]
            self.send(chat_id, "🏅 <b>Твои достижения</b>\n" + "\n".join(rows))
            return
        if cmd == "top":
            top = self.db.top(chat_id)
            ranking = "\n".join(f"{n}. {esc(p['name'] or 'Участник')} — {p['xp']} XP" for n, p in enumerate(top, 1))
            self.send(chat_id, "🏆 <b>Топ активности</b>\n" + (ranking or "Пока нет статистики."))
            return
        if cmd == "report":
            self.report_command(msg, user)
            return
        if cmd in ADMIN_COMMANDS:
            if not self.is_admin(chat_id, user_id, fresh=True):
                self.send(chat_id, "⛔ Эта команда доступна только администраторам.")
                return
            self.admin_command(msg, cmd, args, user)
            return
        if cmd in FUN_COMMANDS:
            if not self.db.get_chat(chat_id)["fun"]:
                self.send(chat_id, "🎮 Развлечения отключены администраторами.")
                return
            self.fun_command(msg, cmd, args, user)

    def target_from_reply(self, msg: dict, actor: dict):
        target = (msg.get("reply_to_message") or {}).get("from")
        if not target:
            raise ValueError("Ответь командой на сообщение участника.")
        if target["id"] == actor["id"]:
            raise ValueError("Нельзя применять эту команду к себе.")
        if target.get("is_bot"):
            raise ValueError("Эта команда не предназначена для ботов.")
        if self.is_admin(msg["chat"]["id"], target["id"], fresh=True):
            raise ValueError("Администраторы защищены от действий бота.")
        return target

    def admin_command(self, msg: dict, cmd: str, args: str, actor: dict) -> None:
        chat_id, admin_id = msg["chat"]["id"], actor["id"]
        try:
            if cmd == 'status':
                cfg = self.db.get_chat(chat_id)
                st = self.db.stats(chat_id)
                self.send(chat_id, runtime_status() +
                          f"\n🛡 Антиспам: {'✅' if cfg['antispam'] else '⏸'}" +
                          f"\n🚩 Открытых жалоб: {st['reports']}" +
                          f"\n⚠️ Активных предупреждений: {st['warnings']}" +
                          "\n🧰 Проверить права бота: /diagnostics")
            elif cmd == 'pin':
                reply = msg.get('reply_to_message') or {}
                target_message = reply.get('message_id')
                if not isinstance(target_message, int) or target_message <= 0:
                    raise ValueError('Ответь /pin на сообщение, которое нужно закрепить.')
                self.call('pinChatMessage', chat_id=chat_id, message_id=target_message, disable_notification=True)
                self.db.log_action(chat_id, admin_id, admin_id, 'pin', f'message {target_message}')
                self.send(chat_id, '📌 Сообщение закреплено.')
            elif cmd == 'unpin':
                reply = msg.get('reply_to_message') or {}
                target_message = reply.get('message_id')
                params = {'chat_id': chat_id}
                if isinstance(target_message, int) and target_message > 0:
                    params['message_id'] = target_message
                self.call('unpinChatMessage', **params)
                self.db.log_action(chat_id, admin_id, admin_id, 'unpin', f'message {target_message or "latest"}')
                self.send(chat_id, '📌 Закрепление снято.')
            elif cmd == "panel":
                url = f"https://t.me/{self.username}?start=panel" if self.username else ""
                self.send(chat_id, "📲 <b>KREW Panel</b>\nОткрой личный чат с ботом и отправь /panel." +
                          ("\n" + esc(url) if url else ""))
            elif cmd == "setup":
                self.send(chat_id, self.settings_text(chat_id), reply_markup=self.settings_keyboard(chat_id))
            elif cmd == "diagnostics":
                me = self.call("getMe")
                myself = self.call("getChatMember", chat_id=chat_id, user_id=me["id"])
                role = myself.get("status", "unknown")
                can_delete = role == "creator" or bool(myself.get("can_delete_messages"))
                can_restrict = role == "creator" or bool(myself.get("can_restrict_members"))
                self.send(chat_id, f"🧰 <b>Диагностика KREW</b>\n🟢 Telegram API: доступен\n"
                                   f"👤 Роль бота: {esc(role)}\n"
                                   f"{'✅' if can_delete else '❌'} Удаление сообщений\n"
                                   f"{'✅' if can_restrict else '❌'} Ограничение участников\n"
                                   f"💾 База SQLite: доступна\n"
                                   "Если есть ❌, открой настройки группы и назначь необходимые права боту.")
            elif cmd == "digest":
                days = self.db.timeline(chat_id, 7)
                messages = sum(day["messages"] for day in days)
                joins = sum(day["joins"] for day in days)
                actions = sum(day["actions"] for day in days)
                self.send(chat_id, "📈 <b>KREW — последние 7 дней</b>\n"
                          f"💬 Сообщений: {messages}\n"
                          f"👥 Новых участников: {joins}\n"
                          f"🛡 Действий модерации: {actions}\n"
                          "\nℹ️ Графики собираются с установки KREW 0.3.0. Время: UTC.")
            elif cmd == "shield":
                cfg = self.db.get_chat(chat_id)
                self.send(chat_id, "🛡 <b>KREW Shield+ · статус</b>\n"
                          f"Массовые упоминания: {'✅' if cfg['antimentions'] else '⏸'} "
                          f"(лимит {cfg['mention_limit']})\n"
                          f"CAPS-спам: {'✅' if cfg['anticaps'] else '⏸'}\n"
                          f"Антиспам: {'✅' if cfg['antispam'] else '⏸'}\n"
                          "Изменить: /setup или Mini App; порог: /mentionlimit 5")
            elif cmd == "mentionlimit":
                if not args.isdigit() or not 3 <= int(args) <= 15:
                    raise ValueError("Формат: /mentionlimit 5 (3–15)")
                self.db.set_setting(chat_id, "mention_limit", int(args), admin_id)
                self.send(chat_id, f"✅ Лимит упоминаний: {int(args)}")
            elif cmd == "stats":
                st = self.db.stats(chat_id)
                self.send(chat_id, f"📊 <b>Статистика KREW</b>\n👥 Участников в учёте: {st['members']}\n💬 Сообщений обработано для статистики: {st['messages']}\n⚠️ Активных предупреждений: {st['warnings']}\n🚩 Открытых жалоб: {st['reports']}\n🛡 Действий модерации за 30 дней: {st['actions']}\n\nУчёт ведётся только с момента запуска бота.")
            elif cmd == "reports":
                count = self.db.stats(chat_id)["reports"]
                keyboard = {"inline_keyboard": [[{"text": "🔐 Открыть жалобы в личке",
                            "url": f"https://t.me/{self.username}?start=reports_{chat_id}"}]]} if self.username else None
                params = {"reply_markup": keyboard} if keyboard else {}
                self.send(chat_id, f"🚩 Жалоб в очереди: {count}\n🔐 Подробности видны только администраторам в личных сообщениях с ботом. "
                                   f"В личке можно также отправить <code>/reports {chat_id}</code>.", **params)
            elif cmd == "warnlimit":
                if not args.isdigit():
                    raise ValueError("Формат: /warnlimit 3 (от 1 до 10)")
                self.db.set_warn_limit(chat_id, int(args))
                self.send(chat_id, f"✅ Порог автомодерации: {int(args)} предупреждений")
            elif cmd == "welcometext":
                if not args:
                    self.db.set_welcome_text(chat_id, "")
                    self.send(chat_id, "✅ Стандартное приветствие восстановлено")
                else:
                    self.db.set_welcome_text(chat_id, args)
                    self.send(chat_id, "✅ Приветствие обновлено. Поддерживается {user} (упоминание).")
            elif cmd == "raid":
                if args.lower() == "off":
                    self.db.raid(chat_id, 0)
                    self.send(chat_id, "✅ Режим анти-рейда выключен")
                else:
                    seconds, _ = parse_duration((args or "15m"))
                    until = int(time.time()) + seconds
                    self.db.raid(chat_id, until)
                    self.send(chat_id, f"🚨 Анти-рейд активирован на {seconds//60} минут. Новые участники будут проходить проверку.")
            elif cmd == "allowlink":
                action, _, value = args.partition(" ")
                if action == "list" or not args:
                    domains = self.db.list_domains(chat_id)
                    self.send(chat_id, "🔗 <b>Разрешённые домены</b>\n" + ("\n".join('• '+esc(d) for d in domains) if domains else "Пусто") + "\nПример: /allowlink add youtube.com")
                elif action in ("add", "del"):
                    domain = normalize_domain(value)
                    ok = self.db.add_domain(chat_id, domain) if action == "add" else self.db.remove_domain(chat_id, domain)
                    self.send(chat_id, "✅ Готово" if ok else "ℹ️ Без изменений (дубликат/лимит/нет такого домена)")
                else:
                    raise ValueError("Формат: /allowlink add домен | del домен | list")
            elif cmd == "setrules":
                if not 3 <= len(args) <= 1200:
                    raise ValueError("Формат: /setrules текст правил (3–1200 символов)")
                self.db.set_rules(chat_id, args)
                self.send(chat_id, "✅ Правила обновлены. Посмотреть: /rules")
            elif cmd == "badword":
                action, _, value = args.partition(" ")
                if action == "list" or not args:
                    words = self.db.list_words(chat_id)
                    lines = ["• " + esc(w) for w in words]
                    body = "\n".join(lines)
                    if len(body) > 3400:
                        body = body[:3400] + "\n… (список обрезан)"
                    self.send(chat_id, "🚫 <b>Запрещённые слова</b>\n" + (body if words else "Список пуст") + "\n\nДобавить: /badword add слово\nУдалить: /badword del слово")
                elif action in ("add", "del"):
                    word = clean_word(value)
                    if action == "add":
                        result = self.db.add_word(chat_id, word)
                        self.send(chat_id, "✅ Слово добавлено" if result else "Не добавлено: уже есть или достигнут лимит 100 слов")
                    else:
                        result = self.db.remove_word(chat_id, word)
                        self.send(chat_id, "✅ Слово удалено" if result else "Такого слова нет")
                    self._words_cache.pop(chat_id, None)
                else:
                    raise ValueError("Формат: /badword add слово | /badword del слово | /badword list")
            elif cmd == "modlog":
                logs = self.db.recent_actions(chat_id)
                rows = [f"{datetime.fromtimestamp(x['timestamp'], timezone.utc):%d.%m %H:%M} UTC · {esc(x['action'])} · ID {x['target_id']}" for x in logs]
                self.send(chat_id, "📋 <b>Последние действия</b>\n" + ("\n".join(rows) if rows else "Пусто"))
            elif cmd == "unban":
                if not args.isdigit():
                    raise ValueError("Формат: /unban 123456789 (числовой Telegram ID)")
                target_id = int(args)
                self.call("unbanChatMember", chat_id=chat_id, user_id=target_id, only_if_banned=True)
                self.db.log_action(chat_id, admin_id, target_id, "unban")
                self.send(chat_id, f"✅ Бан снят: ID {target_id}")
            else:
                target = self.target_from_reply(msg, actor)
                target_id = int(target["id"])
                if cmd == "warnings":
                    self.send(chat_id, f"⚠️ {mention(target)}: {self.db.get_warn(chat_id, target_id)} предупреждений")
                elif cmd == "warn":
                    self.issue_warning(chat_id, target, admin_id, (args or "Нарушение правил")[:160])
                elif cmd == "unwarn":
                    value = self.db.un_warn(chat_id, target_id)
                    self.db.log_action(chat_id, admin_id, target_id, "unwarn", args)
                    self.send(chat_id, f"✅ Предупреждение снято у {mention(target)}. Осталось: {value}")
                elif cmd == "mute":
                    seconds, reason = parse_duration(args)
                    self.restrict(chat_id, target_id, seconds)
                    self.db.log_action(chat_id, admin_id, target_id, "mute", reason)
                    self.send(chat_id, f"🔇 {mention(target)} ограничен на {esc(args.split()[0])}. Причина: {esc(reason)}")
                elif cmd == "unmute":
                    self.restrict(chat_id, target_id, None)
                    self.db.log_action(chat_id, admin_id, target_id, "unmute", args)
                    self.send(chat_id, f"🔊 Ограничение снято с {mention(target)}")
                elif cmd in ("kick", "ban"):
                    self.call("banChatMember", chat_id=chat_id, user_id=target_id)
                    if cmd == "kick":
                        self.call("unbanChatMember", chat_id=chat_id, user_id=target_id, only_if_banned=True)
                    self.db.log_action(chat_id, admin_id, target_id, cmd, args)
                    self.send(chat_id, f"{'👢 Удалён из группы' if cmd == 'kick' else '⛔ Заблокирован'}: {mention(target)}")
        except ValueError as exc:
            self.send(chat_id, "ℹ️ " + esc(exc))
        except TelegramError:
            self.send(chat_id, "❌ Не удалось выполнить действие. Проверь права администратора у бота (в том числе право закрепления сообщений) через настройки группы и /diagnostics.")

    def fun_command(self, msg: dict, cmd: str, args: str, user: dict) -> None:
        chat_id, user_id = msg["chat"]["id"], user["id"]
        if cmd not in {"mission", "claim", "thanks"} and not self._allow_fun(chat_id, user_id, cmd, 10 if cmd != "quiz" else 35):
            return  # Silent cooldown avoids clutter
        if cmd == "mission":
            if not self.db.get_chat(chat_id)["levels"]:
                self.send(chat_id,"ℹ️ Ежедневные задания требуют включённых уровней (/setup).")
                return
            task=self.db.mission(chat_id,user_id)
            state="✅ Награда получена" if task["claimed"] else ("🎁 Награда доступна: /claim" if task["messages"] >= 5 else "Ещё немного активности!")
            self.send(chat_id, f"🎯 <b>Задание на сегодня (UTC)</b>\n"
                      f"{mention(user)} — напиши 5 сообщений с промежутком хотя бы 60 секунд.\n"
                      f"Прогресс: {min(task['messages'],5)}/5\nНаграда: 35 🪙\n{state}")
        elif cmd == "claim":
            if not self.db.get_chat(chat_id)["levels"]:
                self.send(chat_id,"ℹ️ Задания отключены вместе с уровнями.")
                return
            status=self.db.claim_mission(chat_id,user_id)
            self.send(chat_id, {"claimed":f"🏆 {mention(user)}, задание выполнено! +35 🪙",
                                "already":"⏳ Награда за сегодня уже получена.",
                                "not_ready":"🎯 Задание пока не выполнено. Твой прогресс: /mission"}[status])
        elif cmd == "thanks":
            recipient=(msg.get("reply_to_message") or {}).get("from")
            if not recipient or recipient.get("is_bot") or recipient.get("id")==user_id:
                self.send(chat_id,"💜 Ответь /thanks на сообщение другого человека. Одна благодарность в день на чат.")
                return
            ok=self.db.give_thanks(chat_id,user_id,int(recipient['id']))
            if ok:
                self.send(chat_id,f"💜 {mention(user)} поблагодарил {mention(recipient)}! +1 к репутации.")
            else:
                self.send(chat_id,"⏳ Сегодня ты уже благодарил участника этого чата. Завтра (UTC) можно снова.")
        elif cmd == "shop":
            lines = [f"• <code>{code}</code> — {label}, {price} 🪙" for code, (label, price) in BADGES.items()]
            owned = self.db.owned_badges(chat_id, user_id)
            self.send(chat_id, "🛍️ <b>Магазин значков</b>\n" + "\n".join(lines) +
                      "\n\nКупить/надеть: <code>/buy spark</code>\nЗначки сохраняются навсегда в этом чате. " +
                      ("\nТвои значки: " + ", ".join(esc(x) for x in owned) if owned else ""))
        elif cmd == "buy":
            code = args.casefold().strip()
            if code not in BADGES:
                self.send(chat_id, "ℹ️ Выбери значок через /shop и используй /buy код")
                return
            title, price = BADGES[code]
            result = self.db.buy_badge(chat_id, user_id, code, price)
            response = {"purchased": f"✅ Куплен и установлен значок {title} за {price} 🪙!",
                        "equipped": f"✅ Значок {title} установлен бесплатно (уже куплен).",
                        "insufficient": f"🪙 Не хватает монет на {title} ({price}). Играй в /quiz и забирай /daily."}[result]
            self.send(chat_id, response)
        elif cmd == "daily":
            value = 25 + secrets.randbelow(46)
            ok, coins = self.db.daily(chat_id, user_id, human_name(user), value)
            streak = self.db.profile(chat_id, user_id)["daily_streak"]
            self.send(chat_id, f"🎁 {mention(user)} получает <b>{value} 🪙</b>! Баланс: {coins}. Серия: {streak} дн. 🔥" if ok else
                      f"⏳ {mention(user)}, награда уже получена. Следующая после 00:00 UTC. Серия: {streak} дн.")
        elif cmd == "rps":
            # One server-authoritative game per command; only the initiator can play.
            game_id = self.db.create_rps(chat_id, user_id, secrets.randbelow(3), int(time.time()) + 120)
            buttons = {"inline_keyboard": [[{"text": "🪨 Камень", "callback_data":f"rps:{game_id}:0"},
                                            {"text": "✂️ Ножницы", "callback_data":f"rps:{game_id}:1"},
                                            {"text": "📄 Бумага", "callback_data":f"rps:{game_id}:2"}]]}
            self.send(chat_id, f"🎮 <b>Камень · Ножницы · Бумага</b>\n{mention(user)}, выбери ход. У тебя 2 минуты. Победа: +8 монет.", reply_markup=buttons)
        elif cmd == "roll":
            if args and (not args.isdigit() or not 2 <= int(args) <= 1000):
                self.send(chat_id, "🎲 Формат: /roll или /roll 20 (2–1000)")
                return
            sides = int(args) if args else 100
            self.send(chat_id, f"🎲 {mention(user)} бросает кубик d{sides}: <b>{secrets.randbelow(sides)+1}</b>")
        elif cmd == "coin":
            self.send(chat_id, f"🪙 {mention(user)} подбрасывает монету: <b>{secrets.choice(('Орёл', 'Решка'))}</b>")
        elif cmd in {"eightball", "fortune"}:
            if cmd == "eightball" and len(args) < 3:
                self.send(chat_id, "🔮 Спроси так: /eightball получится ли сегодня победить?")
            else:
                self.send(chat_id, f"🔮 {mention(user)}, {esc(secrets.choice(QUOTES))}")
        elif cmd == "duel":
            target = (msg.get("reply_to_message") or {}).get("from")
            if not target or target["id"] == user_id or target.get("is_bot"):
                self.send(chat_id, "⚔️ Ответь /duel на сообщение другого участника.")
                return
            winner, loser = (user, target) if secrets.randbelow(2) == 0 else (target, user)
            self.send(chat_id, f"⚔️ <b>Дуэль!</b> {mention(user)} vs {mention(target)}\n🏅 Победитель: {mention(winner)}\n🎭 {mention(loser)} обещает реванш!")
        elif cmd == "quiz":
            question, choices, correct = secrets.choice(QUIZZES)
            quiz_id = self.db.new_quiz(chat_id, correct)
            if quiz_id is None:
                self.send(chat_id, "⏳ Новую викторину можно запустить через 45 секунд.")
                return
            buttons = {"inline_keyboard": [[{"text": f"{i+1}. {answer}", "callback_data": f"q:{quiz_id}:{i}"}] for i, answer in enumerate(choices)]}
            self.send(chat_id, "🧠 <b>Викторина KREW</b>\n\n" + esc(question) + "\n\nПервый и каждый следующий правильный ответ: +15 🪙\nВремя: 3 минуты.", reply_markup=buttons)


    # ─────── KREW 0.2: join defense and reporting ───────
    def welcome_new(self, chat_id: int, user: dict, cfg: dict) -> None:
        if not cfg["welcome"]:
            return
        template = cfg.get("welcome_text") or "👋 Добро пожаловать, {user}!\nПравила: /rules"
        # Escape custom template, allowing ONLY a special safe HTML mention placeholder.
        formatted = esc(template).replace("{user}", mention(user))
        self.send(chat_id, formatted)

    def handle_newcomers(self, msg: dict, cfg: dict) -> None:
        chat_id = msg["chat"]["id"]
        now = int(time.time())
        newcomers = [u for u in msg["new_chat_members"][:50] if not u.get("is_bot")]
        if not newcomers:
            return
        self.db.track(chat_id, "joins", len(newcomers))
        recent = self._joins[chat_id]
        while recent and recent[0] <= now-60:
            recent.popleft()
        for _ in newcomers:
            recent.append(now)
        if cfg["antiraid"] and len(recent) >= 5 and cfg["raid_until"] <= now:
            self.db.raid(chat_id, now + 900)
            cfg = self.db.get_chat(chat_id)
            self.send(chat_id, "🚨 <b>Возможный рейд:</b> 5+ новых участников за минуту. Включена проверка новичков на 15 минут. /raid off — выключить (админ).")
        for user in newcomers:
            if self.is_admin(chat_id, user["id"], fresh=True):
                continue
            if cfg["captcha"] or cfg["raid_until"] > now:
                self.challenge_newcomer(chat_id, user)
            else:
                self.welcome_new(chat_id, user, cfg)

    def challenge_newcomer(self, chat_id: int, user: dict) -> None:
        """Restrict first, then create challenge. No chat-wide permission changes."""
        user_id = int(user["id"])
        a, b = 2 + secrets.randbelow(8), 1 + secrets.randbelow(8)
        correct_value = a+b
        options = list({correct_value, correct_value+secrets.choice((2,3,4)), max(1,correct_value-secrets.choice((2,3,4)))})
        while len(options) < 3:
            options.append(correct_value + len(options)+4)
        secrets.SystemRandom().shuffle(options)
        correct = options.index(correct_value)
        try:
            self.restrict(chat_id, user_id, 600)
            self.db.new_challenge(chat_id, user_id, f"{a} + {b} = ?", correct, ",".join(map(str,options)), int(time.time())+300)
            buttons = {"inline_keyboard": [[{"text":str(v),"callback_data":f"v:{user_id}:{i}"} for i,v in enumerate(options)]]}
            response = self.send(chat_id, f"🛡 <b>Проверка новичка</b>\n{mention(user)}, реши {a} + {b} = ?\n⏱ 5 минут. Если не ответить — бот исключит из группы.", reply_markup=buttons)
            if isinstance(response, dict) and response.get("message_id"):
                self.db.set_challenge_message(chat_id, user_id, int(response["message_id"]))
        except TelegramError:
            LOGGER.warning("Не получилось ограничить или проверить новичка %s в чате %s — проверьте права", user_id, chat_id)
            # A failed send after successful restrict is detectable in /setup and maintenance.

    def _restore_permissions(self, chat_id: int, user_id: int) -> None:
        # Use the group default permissions instead of granting extra access.
        chat = self.call("getChat", chat_id=chat_id)
        defaults = (chat or {}).get("permissions") or {"can_send_messages": True}
        self.call("restrictChatMember", chat_id=chat_id, user_id=user_id,
                  permissions=defaults, use_independent_chat_permissions=True)

    def verify_newcomer(self, chat_id: int, user_id: int, choice: int, msg: dict) -> str:
        challenge = self.db.challenge(chat_id, user_id)
        if not challenge:
            return "Проверка уже завершена"
        if challenge["message_id"] and challenge["message_id"] != msg.get("message_id"):
            return "Устаревшая кнопка"
        result = self.db.attempt_challenge(chat_id, user_id, choice)
        if result == "correct":
            try:
                self._restore_permissions(chat_id, user_id)
            except TelegramError:
                return "Не удалось снять ограничение. Сообщи администратору"
            self.db.delete_challenge(chat_id, user_id)
            self.call("editMessageText", chat_id=chat_id, message_id=msg["message_id"],
                      text="✅ Проверка пройдена! Добро пожаловать в чат.")
            return "Добро пожаловать!"
        return {"wrong":"Неверно, попробуй ещё раз", "expired":"Время истекло", "missing":"Проверка не найдена"}.get(result, "Ошибка")

    def maintenance(self, now: int | None = None) -> None:
        """Run once per polling cycle: remove expired challenges and stale raid mode."""
        now = int(time.time()) if now is None else now
        for item in self.db.expired_challenges(now):
            cid, uid = item["chat_id"], item["user_id"]
            try:
                # Kick = ban then unban. If unban fails, retry on next maintenance
                # (unbanChatMember with only_if_banned ensures no unexpected removal).
                self.call("banChatMember", chat_id=cid, user_id=uid)
                self.call("unbanChatMember", chat_id=cid, user_id=uid, only_if_banned=True)
                self.db.delete_challenge(cid, uid)
                self.db.log_action(cid, None, uid, "captcha_timeout")
                if item["message_id"]:
                    try:
                        self.call("deleteMessage", chat_id=cid, message_id=item["message_id"])
                    except TelegramError:
                        pass
            except TelegramError:
                LOGGER.warning("Captcha timeout failed in chat %s for member %s", cid, uid)

    def report_command(self, msg: dict, actor: dict) -> None:
        chat_id = msg["chat"]["id"]
        target_msg = msg.get("reply_to_message") or {}
        target = target_msg.get("from") or {}
        if target_msg.get("sender_chat") or not target.get("id") or target.get("id") == actor["id"] or target.get("is_bot"):
            self.send(chat_id, "🚩 Ответь /report на сообщение другого участника.")
            return
        if not self._allow_fun(chat_id, actor["id"], "report", 30):
            return
        result = self.db.report(chat_id, actor["id"], target["id"], int(target_msg["message_id"]))
        self.send(chat_id, {"created":"🚩 Жалоба отправлена. Статус: /myreports в личке с ботом (сначала нажми /start). Содержимое сообщения не сохраняется.",
                            "duplicate":"ℹ️ Ты уже жаловался на это сообщение.",
                            "limited":"⏳ Лимит: до 3 жалоб в час."}[result])

    def private_reports(self, private_id: int, user_id: int, group_id_text: str) -> None:
        try:
            group_id = int(group_id_text)
        except ValueError:
            self.send(private_id, "Используй ссылку из /reports в группе или отправь /reports ID_группы.")
            return
        if group_id >= 0 or not self.is_admin(group_id, user_id, fresh=True):
            self.send(private_id, "⛔ Нет доступа: необходимо быть администратором указанной группы.")
            return
        entries = self.db.reports(group_id)
        if not entries:
            self.send(private_id, "✅ Открытых жалоб для этой группы нет.")
            return
        self.send(private_id, f"🔐 <b>Модерация чата {group_id}</b>\nОткрытых жалоб: {len(entries)} (показаны последние 10).")
        for item in entries:
            keyboard = {"inline_keyboard": [[
                {"text":"❌ Отклонить с причиной", "callback_data":f"rep:{group_id}:{item['id']}:reject"},
                {"text":"⚠️ Предупредить", "callback_data":f"rep:{group_id}:{item['id']}:warn"}
            ]]}
            self.send(private_id, f"🚩 <b>Жалоба #{item['id']}</b>\nОт ID: <code>{item['reporter_id']}</code>\nНа ID: <code>{item['target_id']}</code>\nСообщение: <code>{item['target_message_id']}</code>\nПолный текст сообщения не сохраняется.", reply_markup=keyboard)

    def notify_reporter(self, entry: dict, status: str, reason: str) -> str:
        """Notify ONLY users who started private chat. Failure must not roll back decision."""
        uid=int(entry["reporter_id"])
        if not self.db.notifications_allowed(uid):
            exists=self.db.conn.execute("SELECT 1 FROM private_users WHERE user_id=?",(uid,)).fetchone()
            delivery="disabled" if exists else "not_started"
        else:
            label={"rejected":"❌ Отклонена", "warned":"⚠️ Подтверждена", "closed":"✅ Закрыта"}[status]
            chat=self.db.known_chat(entry["chat_id"]) or {}
            message=(f"📩 <b>Решение по жалобе #{entry['id']}</b>\n"
                     f"Группа: {esc(chat.get('title') or entry['chat_id'])}\n"
                     f"Решение: {label}\n"
                     f"Причина: {esc(reason)}\n\n"
                     "Посмотреть обращения: /myreports\nОтключить уведомления: /notify off")
            try:
                self.send(uid,message)
                delivery="sent"
            except TelegramError:
                delivery="failed"
                LOGGER.info("Report %s private notification unavailable",entry['id'])
        self.db.record_delivery(entry["id"], entry["chat_id"], delivery)
        return delivery

    def notify_report_target(self, entry: dict, reason: str) -> str:
        """Send a private warning to the reported member, without identifying reporter."""
        uid=int(entry["target_id"])
        if not self.db.notifications_allowed(uid):
            exists=self.db.conn.execute("SELECT 1 FROM private_users WHERE user_id=?",(uid,)).fetchone()
            delivery="disabled" if exists else "not_started"
        else:
            chat=self.db.known_chat(entry["chat_id"]) or {}
            text=(f"⚠️ <b>Предупреждение от модерации</b>\n"
                  f"Группа: {esc(chat.get('title') or entry['chat_id'])}\n"
                  f"Причина: {esc(reason)}\n\n"
                  "Если не согласен с решением, обратись к администрации группы. "
                  "Имя автора жалобы не раскрывается.\n"
                  "Настройки уведомлений: /notify off")
            try:
                self.send(uid,text)
                delivery="sent"
            except TelegramError:
                delivery="failed"
                LOGGER.info("Report %s target DM unavailable",entry['id'])
        self.db.record_target_delivery(entry["id"],entry["chat_id"],delivery)
        return delivery

    def decide_report(self, chat_id: int, report_id: int, actor_id: int, action: str, reason: str) -> dict:
        """Shared decision implementation for Telegram and Mini App.

        Decision is committed before any external Telegram call. Duplicate requests are safe.
        """
        entry=self.db.get_report(report_id,chat_id)
        if entry is None or entry["status"]!="open":
            raise ValueError("Жалоба уже рассмотрена или не найдена")
        if action == "warn":
            # Fail closed if Telegram cannot confirm privileges of target.
            member=self.call("getChatMember",chat_id=chat_id,user_id=entry["target_id"])
            if member.get("status") in {"creator", "administrator"}:
                raise ValueError("Нельзя предупредить администратора")
            outcome, note="warned", "Нарушение подтверждено модератором"
        elif action == "reject":
            outcome, note="rejected", reason.strip() if isinstance(reason,str) else ""
        elif action == "close":
            outcome, note="closed", "Закрыта модератором без санкций"
        else:
            raise ValueError("Недопустимое решение")
        if not self.db.decide_report(report_id,chat_id,actor_id,outcome,note):
            raise ValueError("Жалоба уже рассмотрена")
        warning_recorded=False
        warning_sent=None
        if outcome=="warned":
            warning_recorded=True
            try:
                self.issue_warning(chat_id,{"id":entry["target_id"],"first_name":"Участник"},actor_id,"По жалобе участника")
                warning_sent=True
            except TelegramError:
                # A Telegram message may fail after the warning is persisted.
                LOGGER.warning("Warning delivery failed for report %s",report_id)
                warning_sent=False
        delivery=self.notify_reporter(entry,outcome,note)
        target_delivery=self.notify_report_target(entry,"Нарушение правил чата") if outcome=="warned" else "not_applicable"
        return {"status":outcome,"reason":note,"notification_status":delivery,
                "target_notification_status":target_delivery,
                "warning_recorded":warning_recorded,"warning_notification_sent":warning_sent}

    def private_reject(self, private_id: int, user_id: int, args: str) -> None:
        parts=(args or "").split(maxsplit=2)
        if len(parts)!=3 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit():
            self.send(private_id,"Формат: <code>/reject -1001234567 42 Причина отклонения</code>")
            return
        group_id,rid,reason=int(parts[0]),int(parts[1]),parts[2]
        if group_id>=0 or not self.is_admin(group_id,user_id,fresh=True):
            self.send(private_id,"⛔ Только действующий администратор группы может решать жалобы.")
            return
        try:
            result=self.decide_report(group_id,rid,user_id,"reject",reason)
        except (ValueError,TelegramError) as exc:
            self.send(private_id,"⚠️ "+esc(str(exc)))
            return
        self.send(private_id,f"✅ Жалоба #{rid} отклонена.\nПричина: {esc(result['reason'])}\nУведомление: {esc(result['notification_status'])}.")

    def resolve_report_callback(self, chat_id: int, actor: dict, report_id: int, action: str, msg: dict) -> str:
        if not self.is_admin(chat_id, actor.get("id", 0), fresh=True):
            return "Только для администраторов"
        entry=self.db.get_report(report_id,chat_id)
        if entry is None or entry["status"]!="open":
            return "Жалоба уже обработана"
        if action=="reject":
            # ForceReply prompt; ID is checked again when the reason is submitted.
            self.send(msg["chat"]["id"],
                      f"❌ <b>Отклонение жалобы #{report_id}</b>\n"
                      "Ответь на это сообщение причиной (5–300 символов).\n"
                      f"KREW_REJECT {chat_id} {report_id}",
                      reply_markup={"force_reply":True,"input_field_placeholder":"Причина отклонения (5–300 символов)"})
            return "Отправил запрос причины в личные сообщения"
        if action not in {"warn","close"}:
            return "Неизвестное действие"
        try:
            result=self.decide_report(chat_id,report_id,int(actor["id"]),action,"")
        except ValueError as exc:
            return str(exc)
        try:
            self.call("editMessageText",chat_id=msg["chat"]["id"],message_id=msg["message_id"],
                      text=f"✅ Жалоба #{report_id}: {esc(result['reason'])}")
        except TelegramError:
            LOGGER.info("Could not edit report callback message %s",report_id)
        return "Рассмотрено · ЛС: " + result["notification_status"]
