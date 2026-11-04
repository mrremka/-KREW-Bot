"""KREW Mini App HTTP server. Standard library, signed Telegram initData only.

Put this HTTP service behind HTTPS reverse proxy before use in Telegram.
DB connections are short-lived per request: safe alongside polling in another thread.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
from krew.api import TelegramAPI, TelegramError
from krew.roles import clean_tag
from krew.db import Database, FIELDS
from krew.rules import clean_word, normalize_domain
from krew.core import BotCore

STATIC = Path(__file__).resolve().parent / "static"
LOG = logging.getLogger("krew.web")
CHAT_RE = re.compile(r"^/api/chats/(-\d+)/(overview|settings|reports)$")
REPORT_RE = re.compile(r"^/api/chats/(-\d+)/reports/(\d+)/(close|warn|reject)$")
EXTRA_RE = re.compile(r"^/api/chats/(-\d+)/(analytics|audit|rulesets|words|domains|community)$")
ROLES_RE = re.compile(r"^/api/chats/(-\d+)/roles$")


class WebError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def verify_init_data(raw: str, token: str, now: int | None = None, ttl: int = 3600) -> dict:
    """Verify HMAC and freshness; reject duplicate params and user-controlled forged IDs."""
    if not isinstance(raw, str) or not 1 <= len(raw) <= 8000 or not token:
        raise WebError(401, "Нет данных авторизации Telegram")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
        data = dict(pairs)
        if len(data) != len(pairs) or not re.fullmatch(r"[0-9a-f]{64}", data.get("hash", "")):
            raise ValueError("invalid hash")
        date = int(data["auth_date"])
        now = int(time.time() if now is None else now)
        if date > now + 60 or date < now - ttl:
            raise ValueError("expired")
        check = "\n".join(f"{k}={v}" for k,v in sorted(pairs) if k != "hash")
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        correct = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(data["hash"], correct):
            raise ValueError("invalid signature")
        user = json.loads(data["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            raise ValueError("no user")
        return user
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError) as exc:
        raise WebError(401, "Сессия Telegram недействительна или устарела") from None


class Application:
    def __init__(self, token: str, db_path: Path | str, api=None):
        self.token = token
        self.db_path = Path(db_path)
        self.api = api if api is not None else TelegramAPI(token)

    def user(self, auth: str) -> dict:
        if not auth.startswith("tma "):
            raise WebError(401, "Откройте панель через Telegram")
        return verify_init_data(auth[4:], self.token)

    def authorize_chat(self, db: Database, chat_id: int, user_id: int) -> dict:
        if chat_id >= 0:
            raise WebError(404, "Чат не найден")
        chat = db.known_chat(chat_id)
        if not chat:
            raise WebError(404, "Чат не найден")
        try:
            member = self.api.call("getChatMember", chat_id=chat_id, user_id=user_id)
        except TelegramError:
            raise WebError(503, "Не удалось проверить права в Telegram") from None
        if member.get("status") not in ("creator", "administrator"):
            raise WebError(403, "Нужны права администратора группы")
        return chat

    def process(self, method: str, path: str, auth: str = "", data=None) -> tuple[int, dict]:
        """Return a (status, JSON payload) tuple. Never trust a chat ID from the client."""
        try:
            user = self.user(auth)
            user_id = user["id"]
            with_db = Database(self.db_path)
            try:
                if path == "/api/chats" and method == "GET":
                    owned = []
                    for chat in with_db.known_chats():
                        try:
                            member = self.api.call("getChatMember", chat_id=chat["chat_id"], user_id=user_id)
                            if member.get("status") in ("creator", "administrator"):
                                owned.append(chat)
                        except TelegramError:
                            continue
                    return 200, {"chats": owned}
                match = CHAT_RE.fullmatch(path)
                if match:
                    chat_id, endpoint = int(match[1]), match[2]
                    self.authorize_chat(with_db, chat_id, user_id)
                    if endpoint == "overview" and method == "GET":
                        return 200, {"stats":with_db.stats(chat_id),"chat":with_db.known_chat(chat_id),
                                     "recent":with_db.recent_actions(chat_id)}
                    if endpoint == "settings":
                        if method == "GET":
                            cfg = with_db.known_chat(chat_id)
                            return 200, {"settings": {k: bool(cfg[k]) for k in FIELDS} |
                                    {"warn_limit":cfg["warn_limit"], "rules":cfg["rules"], "welcome_text":cfg["welcome_text"], "mention_limit":cfg["mention_limit"]}}
                        if method == "PATCH":
                            if not isinstance(data, dict) or set(data) != {"field", "value"}:
                                raise WebError(400, "Нужно указать одно поле и значение")
                            try:
                                cfg = with_db.set_setting(chat_id, data["field"], data["value"], user_id)
                            except (ValueError, TypeError, KeyError):
                                raise WebError(400, "Неверное значение настройки") from None
                            return 200, {"settings": {k: bool(cfg[k]) for k in FIELDS} |
                                    {"warn_limit":cfg["warn_limit"], "rules":cfg["rules"], "welcome_text":cfg["welcome_text"], "mention_limit":cfg["mention_limit"]}}
                    if endpoint == "reports" and method == "GET":
                        return 200, {"reports":with_db.reports(chat_id),"history":with_db.report_history(chat_id)}
                roles_match = ROLES_RE.fullmatch(path)
                if roles_match:
                    chat_id = int(roles_match[1])
                    self.authorize_chat(with_db, chat_id, user_id)
                    if method == "GET":
                        return 200, {"roles": with_db.role_tags(chat_id)}
                    if method == "POST":
                        if (not isinstance(data, dict) or set(data) != {"user_id", "tag"}
                                or type(data["user_id"]) is not int or data["user_id"] <= 0
                                or data["user_id"] >= 2**52 or not isinstance(data["tag"], str)):
                            raise WebError(400, "Нужны Telegram ID участника и название роли")
                        target_id = data["user_id"]
                        try:
                            tag = clean_tag(data["tag"]) if data["tag"].strip() else ""
                        except ValueError as exc:
                            raise WebError(400, str(exc)) from None
                        try:
                            member = self.api.call("getChatMember", chat_id=chat_id, user_id=target_id)
                        except TelegramError:
                            raise WebError(503, "Не удалось проверить участника в Telegram") from None
                        if member.get("status") not in ("member", "restricted"):
                            raise WebError(409, "Теги доступны только обычным участникам группы")
                        if member.get("status") == "restricted" and not member.get("is_member", True):
                            raise WebError(409, "Участник не состоит в группе")
                        try:
                            self.api.call("setChatMemberTag", chat_id=chat_id,
                                          user_id=target_id, tag=tag)
                        except TelegramError:
                            raise WebError(403, "Нужно право бота can_manage_tags для управления тегами") from None
                        who = member.get("user") or {}
                        name = " ".join(filter(None, (who.get("first_name", ""),
                                                       who.get("last_name", ""))))
                        with_db.set_role_tag(chat_id, target_id, tag, user_id, name)
                        with_db.log_action(chat_id, user_id, target_id,
                                           "role" if tag else "unrole", tag)
                        return 200, {"roles": with_db.role_tags(chat_id)}
                    raise WebError(405, "Метод не разрешён")
                match = EXTRA_RE.fullmatch(path)
                if match:
                    chat_id, endpoint = int(match[1]), match[2]
                    self.authorize_chat(with_db, chat_id, user_id)
                    if endpoint == "analytics" and method == "GET":
                        return 200, {"timeline":with_db.timeline(chat_id, 14), "stats":with_db.stats(chat_id),
                                     "top":with_db.top(chat_id, 5)}
                    if endpoint == "community" and method == "GET":
                        return 200, {"community":with_db.community(chat_id)}
                    if endpoint == "audit" and method == "GET":
                        return 200, {"audit":with_db.audit(chat_id),"recent":with_db.recent_actions(chat_id)}
                    if endpoint == "rulesets" and method == "GET":
                        return 200, {"words":with_db.list_words(chat_id),"domains":with_db.list_domains(chat_id)}
                    if endpoint in ("words","domains") and method == "POST":
                        if not isinstance(data,dict) or set(data) != {"action","value"} or data.get("action") not in {"add","remove"} or not isinstance(data.get("value"),str):
                            raise WebError(400,"Неверный формат")
                        try:
                            value = clean_word(data["value"]) if endpoint == "words" else normalize_domain(data["value"])
                        except ValueError as exc:
                            raise WebError(400,str(exc)) from None
                        if endpoint == "words":
                            changed = with_db.add_word(chat_id,value) if data["action"]=="add" else with_db.remove_word(chat_id,value)
                        else:
                            changed = with_db.add_domain(chat_id,value) if data["action"]=="add" else with_db.remove_domain(chat_id,value)
                        if not changed:
                            raise WebError(409,"Не удалось изменить список: дубликат, лимит или значение не найдено")
                        with_db.record_audit(chat_id,user_id,endpoint+"_"+data["action"],"",value)
                        return 200, {"words":with_db.list_words(chat_id),"domains":with_db.list_domains(chat_id)}
                match = REPORT_RE.fullmatch(path)
                if match and method == "POST":
                    chat_id, rid, action = int(match[1]), int(match[2]), match[3]
                    self.authorize_chat(with_db, chat_id, user_id)
                    if action=="reject":
                        if not isinstance(data,dict) or set(data)!={"reason"} or not isinstance(data["reason"],str):
                            raise WebError(400,"Укажите причину отклонения (5–300 символов)")
                        reason=data["reason"]
                    elif data not in ({},None):
                        raise WebError(400,"Неверный формат решения")
                    else:
                        reason=""
                    core=BotCore(self.api,with_db)
                    try:
                        result=core.decide_report(chat_id,rid,user_id,action,reason)
                    except ValueError as exc:
                        msg=str(exc)
                        if "Нельзя предупредить" in msg:
                            raise WebError(403,msg) from None
                        raise WebError(409 if "уже" in msg else 400,msg) from None
                    except TelegramError:
                        raise WebError(503,"Не удалось проверить статус участника") from None
                    # Keep the old notification_sent key for compatible Mini App clients.
                    result["notification_sent"]=(result["warning_notification_sent"] is not False)
                    return 200,result
                raise WebError(404, "Не найдено")
            finally:
                with_db.close()
        except WebError as exc:
            return exc.status, {"error":str(exc)}


class Handler(BaseHTTPRequestHandler):
    server_version = "KREW-web"
    def log_message(self, fmt, *args):
        """Avoid recording request lines and query strings in access logs."""
        method = self.command if getattr(self, "command", None) in {"GET", "POST", "PATCH", "HEAD"} else "OTHER"
        code = str(args[1]) if fmt == '"%s" %s %s' and len(args) == 3 and str(args[1]).isdigit() else "unknown"
        LOG.info("HTTP %s response=%s", method, code)

    def _write(self, code, blob: bytes, content_type="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(blob)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org")
        self.end_headers()
        self.wfile.write(blob)

    def _handle(self, method):
        path = urlsplit(self.path).path
        if method == "GET" and path in ("/", "/index.html", "/app.js", "/style.css"):
            name = "index.html" if path in ("/", "/index.html") else path[1:]
            mime = {"index.html":"text/html; charset=utf-8", "app.js":"application/javascript; charset=utf-8", "style.css":"text/css; charset=utf-8"}[name]
            self._write(200,(STATIC/name).read_bytes(),mime)
            return
        if path == "/health" and method == "GET":
            self._write(200,b'{"status":"ok"}')
            return
        if not path.startswith("/api/"):
            self._write(404,'{"error":"Не найдено"}'.encode("utf-8"))
            return
        if method not in {"GET","POST","PATCH"}:
            self._write(405,'{"error":"Метод не разрешён"}'.encode("utf-8"))
            return
        try:
            length = int(self.headers.get("Content-Length","0"))
            if length > 8192 or length < 0:
                raise WebError(413,"Слишком большой запрос")
            body = None
            if method in {"POST","PATCH"}:
                if self.headers.get("Content-Type","").split(";")[0] != "application/json":
                    raise WebError(415,"Ожидался JSON")
                body = json.loads(self.rfile.read(length)) if length else {}
            code, payload = self.server.app.process(method,path,self.headers.get("Authorization",""),body)
        except (ValueError, json.JSONDecodeError):
            code, payload = 400,{"error":"Неверный JSON"}
        except WebError as exc:
            code, payload = exc.status,{"error":str(exc)}
        except Exception:
            LOG.exception("Web request failed")
            code, payload = 500,{"error":"Внутренняя ошибка"}
        self._write(code,json.dumps(payload,ensure_ascii=False).encode("utf-8"))

    def do_GET(self): self._handle("GET")
    def do_PATCH(self): self._handle("PATCH")
    def do_POST(self): self._handle("POST")


def start_server(token: str, db_path: Path | str, host: str = "127.0.0.1", port: int = 8090, api=None):
    """Run HTTP server in a daemon thread and return server for clean shutdown."""
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.app = Application(token, db_path, api)
    threading.Thread(target=httpd.serve_forever, name="krew-web", daemon=True).start()
    return httpd
