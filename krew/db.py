"""Small SQLite repository. No chat texts or message contents are stored."""
from __future__ import annotations
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIELDS = frozenset({"antispam", "antilinks", "welcome", "fun", "levels", "captcha", "antiforward", "antiraid", "antimentions", "anticaps"})

class Database:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._init()

    def _init(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
            antispam INTEGER NOT NULL DEFAULT 1, antilinks INTEGER NOT NULL DEFAULT 0,
            welcome INTEGER NOT NULL DEFAULT 1, fun INTEGER NOT NULL DEFAULT 1,
            levels INTEGER NOT NULL DEFAULT 1,
            rules TEXT NOT NULL DEFAULT 'Уважайте друг друга. Без спама и оскорблений.',
            warn_limit INTEGER NOT NULL DEFAULT 3,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS members (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT '', xp INTEGER NOT NULL DEFAULT 0,
            coins INTEGER NOT NULL DEFAULT 0, messages INTEGER NOT NULL DEFAULT 0,
            last_xp INTEGER NOT NULL DEFAULT 0, last_daily TEXT NOT NULL DEFAULT '',
            active_badge TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS owned_badges (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, badge TEXT NOT NULL,
            PRIMARY KEY (chat_id, user_id, badge)
        );
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS bad_words (
            chat_id INTEGER NOT NULL, word TEXT NOT NULL,
            PRIMARY KEY (chat_id, word)
        );
        CREATE TABLE IF NOT EXISTS modlog (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            admin_id INTEGER, target_id INTEGER NOT NULL,
            action TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
            timestamp INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_modlog_chat ON modlog(chat_id, id DESC);
        CREATE TABLE IF NOT EXISTS quizzes (
            quiz_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL, correct INTEGER NOT NULL,
            expires INTEGER NOT NULL, created INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quiz_answers (
            quiz_id INTEGER NOT NULL, user_id INTEGER NOT NULL, correct INTEGER NOT NULL,
            PRIMARY KEY (quiz_id, user_id)
        );
        """)
        # 0.2.0 additions: preserve all 0.1.0 data with additive migrations.
        chat_columns = {r[1] for r in self.conn.execute("PRAGMA table_info(chats)")}
        for name, spec in {
            "captcha": "INTEGER NOT NULL DEFAULT 0",
            "antiforward": "INTEGER NOT NULL DEFAULT 0",
            "antiraid": "INTEGER NOT NULL DEFAULT 0",
            "raid_until": "INTEGER NOT NULL DEFAULT 0",
            "welcome_text": "TEXT NOT NULL DEFAULT ''",
            "antimentions": "INTEGER NOT NULL DEFAULT 0",
            "anticaps": "INTEGER NOT NULL DEFAULT 0",
            "mention_limit": "INTEGER NOT NULL DEFAULT 5",
        }.items():
            if name not in chat_columns:
                self.conn.execute(f"ALTER TABLE chats ADD COLUMN {name} {spec}")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS allowed_domains (
            chat_id INTEGER NOT NULL, domain TEXT NOT NULL,
            PRIMARY KEY (chat_id, domain)
        );
        CREATE TABLE IF NOT EXISTS challenges (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL DEFAULT 0,
            question TEXT NOT NULL, correct INTEGER NOT NULL,
            options TEXT NOT NULL, expires INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_challenges_expires ON challenges(expires);
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            reporter_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
            target_message_id INTEGER NOT NULL, created INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', resolved_by INTEGER,
            UNIQUE(chat_id, reporter_id, target_message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_reports_chat_status ON reports(chat_id, status, id DESC);
        CREATE TABLE IF NOT EXISTS rps_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, bot_choice INTEGER NOT NULL,
            expires INTEGER NOT NULL, settled INTEGER NOT NULL DEFAULT 0
        );
        """)
        # 1.0 RC: report decisions with reasons, delivery statuses, private opt-in.
        report_columns = {r[1] for r in self.conn.execute("PRAGMA table_info(reports)")}
        for name, spec in {
            "decision_reason": "TEXT NOT NULL DEFAULT ''",
            "resolved_at": "INTEGER NOT NULL DEFAULT 0",
            "notified_at": "INTEGER NOT NULL DEFAULT 0",
            "notification_status": "TEXT NOT NULL DEFAULT 'pending'",
            "target_notification_status": "TEXT NOT NULL DEFAULT 'pending'",
        }.items():
            if name not in report_columns:
                self.conn.execute(f"ALTER TABLE reports ADD COLUMN {name} {spec}")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS private_users (
            user_id INTEGER PRIMARY KEY,
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            started_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """)
        # 1.0 RC2: release announcements are OPT-IN and independent of report notifications.
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(private_users)")}
        if "news_enabled" not in columns:
            self.conn.execute("ALTER TABLE private_users ADD COLUMN news_enabled INTEGER NOT NULL DEFAULT 0")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS news_releases (
            version TEXT PRIMARY KEY, text TEXT NOT NULL, created INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_deliveries (
            version TEXT NOT NULL, user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            retry_at INTEGER NOT NULL DEFAULT 0, delivered_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(version, user_id),
            FOREIGN KEY(version) REFERENCES news_releases(version)
        );
        CREATE INDEX IF NOT EXISTS idx_news_deliveries_pending
          ON news_deliveries(status,retry_at);
        """)
        # 0.3: chart history and setting-change audit, no message content stored.
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_activity (
          chat_id INTEGER NOT NULL, day TEXT NOT NULL,
          messages INTEGER NOT NULL DEFAULT 0,
          joins INTEGER NOT NULL DEFAULT 0,
          actions INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(chat_id, day)
        );
        CREATE TABLE IF NOT EXISTS setting_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_id INTEGER NOT NULL, actor_id INTEGER NOT NULL,
          field TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
          created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_setting_audit_chat ON setting_audit(chat_id, id DESC);
        """)
        # 0.6: earned participation missions and one genuine thank-you per giver/day.
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS member_day (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, day TEXT NOT NULL,
            messages INTEGER NOT NULL DEFAULT 0, claimed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat_id, user_id, day)
        );
        CREATE INDEX IF NOT EXISTS idx_member_day_day ON member_day(day);
        CREATE TABLE IF NOT EXISTS kudos (
            chat_id INTEGER NOT NULL, giver_id INTEGER NOT NULL, day TEXT NOT NULL,
            receiver_id INTEGER NOT NULL,
            PRIMARY KEY(chat_id,giver_id,day)
        );
        CREATE INDEX IF NOT EXISTS idx_kudos_day ON kudos(day);
        """)
        # RC9: visible Telegram role tags and bounded, explicit voice requests.
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS role_tags (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            tag TEXT NOT NULL, assigned_by INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_role_tags_chat ON role_tags(chat_id, tag);
        CREATE TABLE IF NOT EXISTS voice_usage (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            day TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat_id, user_id, day)
        );
        """)
        self.conn.execute("DELETE FROM voice_usage WHERE day < ?",
                          ((datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat(),))
        member_column_names = {r[1] for r in self.conn.execute("PRAGMA table_info(members)")}
        if "reputation" not in member_column_names:
            self.conn.execute("ALTER TABLE members ADD COLUMN reputation INTEGER NOT NULL DEFAULT 0")
        # Forward-compatible migration for databases created by early previews.
        columns = [r[1] for r in self.conn.execute("PRAGMA table_info(members)")]
        if "active_badge" not in columns:
            self.conn.execute("ALTER TABLE members ADD COLUMN active_badge TEXT NOT NULL DEFAULT ''")
        member_columns = {r[1] for r in self.conn.execute("PRAGMA table_info(members)")}
        if "daily_streak" not in member_columns:
            self.conn.execute("ALTER TABLE members ADD COLUMN daily_streak INTEGER NOT NULL DEFAULT 0")
        # Keep only 30 days of moderation actions and old quiz data.
        cutoff = int(time.time()) - 30 * 86400
        self.conn.execute("DELETE FROM modlog WHERE timestamp < ?", (cutoff,))
        self.conn.execute("DELETE FROM quiz_answers WHERE quiz_id IN (SELECT quiz_id FROM quizzes WHERE created < ?)", (cutoff,))
        self.conn.execute("DELETE FROM quizzes WHERE created < ?", (cutoff,))
        self.conn.execute("DELETE FROM reports WHERE created < ?", (int(time.time()) - 30*86400,))
        self.conn.execute("DELETE FROM rps_games WHERE expires < ?", (int(time.time()) - 86400,))
        self.conn.execute("DELETE FROM daily_activity WHERE day < ?", ((datetime.now(timezone.utc)-timedelta(days=91)).date().isoformat(),))
        self.conn.execute("DELETE FROM setting_audit WHERE created < ?", (cutoff,))
        keep_day = (datetime.now(timezone.utc) - timedelta(days=91)).date().isoformat()
        self.conn.execute("DELETE FROM member_day WHERE day < ?", (keep_day,))
        self.conn.execute("DELETE FROM kudos WHERE day < ?", (keep_day,))

    def close(self) -> None:
        self.conn.close()

    def set_role_tag(self, chat_id: int, user_id: int, tag: str, actor_id: int,
                     name: str = "") -> None:
        """Call only after Telegram accepted the visible member tag."""
        self.ensure_chat(chat_id)
        self.ensure_member(chat_id, user_id, name)
        if tag:
            self.conn.execute("""INSERT INTO role_tags(chat_id, user_id, tag, assigned_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                  tag=excluded.tag, assigned_by=excluded.assigned_by,
                  updated_at=excluded.updated_at""",
                (chat_id, user_id, tag, actor_id, int(time.time())))
        else:
            self.conn.execute("DELETE FROM role_tags WHERE chat_id=? AND user_id=?",
                              (chat_id, user_id))

    def role_tag(self, chat_id: int, user_id: int) -> str:
        row = self.conn.execute("SELECT tag FROM role_tags WHERE chat_id=? AND user_id=?",
                                (chat_id, user_id)).fetchone()
        return str(row["tag"]) if row else ""

    def role_tags(self, chat_id: int, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("""SELECT r.user_id, r.tag, COALESCE(m.name,'') AS name
            FROM role_tags r LEFT JOIN members m
              ON m.chat_id=r.chat_id AND m.user_id=r.user_id
            WHERE r.chat_id=? ORDER BY r.updated_at DESC LIMIT ?""",
            (chat_id, min(30, max(1, limit)))).fetchall()
        return [dict(row) for row in rows]

    def reserve_voice_request(self, chat_id: int, user_id: int,
                              daily_limit: int = 3) -> bool:
        """Reserve a daily quota before sending any audio to the speech API."""
        day = datetime.now(timezone.utc).date().isoformat()
        self.conn.execute("""INSERT OR IGNORE INTO voice_usage(chat_id,user_id,day,used)
                             VALUES(?,?,?,0)""", (chat_id,user_id,day))
        cursor = self.conn.execute("""UPDATE voice_usage SET used=used+1
                    WHERE chat_id=? AND user_id=? AND day=? AND used<?""",
                    (chat_id,user_id,day,daily_limit))
        return bool(cursor.rowcount)

    def remaining_voice_requests(self, chat_id: int, user_id: int,
                                 daily_limit: int = 3) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute("SELECT used FROM voice_usage WHERE chat_id=? AND user_id=? AND day=?",
                                (chat_id,user_id,day)).fetchone()
        return max(0,daily_limit-(int(row["used"]) if row else 0))

    def ensure_chat(self, chat_id: int, title: str = "") -> dict:
        self.conn.execute("INSERT OR IGNORE INTO chats(chat_id, title) VALUES (?, ?)", (chat_id, title[:128]))
        if title:
            self.conn.execute("UPDATE chats SET title=? WHERE chat_id=?", (title[:128], chat_id))
        return dict(self.conn.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone())

    def get_chat(self, chat_id: int) -> dict:
        return self.ensure_chat(chat_id)

    def toggle(self, chat_id: int, field: str, actor_id: int = 0) -> dict:
        if field not in FIELDS:
            raise ValueError("Unknown setting")
        current = self.get_chat(chat_id)
        return self.set_setting(chat_id, field, not bool(current[field]), actor_id)

    def set_setting(self, chat_id: int, field: str, value, actor_id: int = 0) -> dict:
        if field not in FIELDS and field not in {"warn_limit", "rules", "welcome_text", "mention_limit"}:
            raise ValueError("Unknown setting")
        if field in FIELDS:
            if type(value) is not bool:
                raise ValueError("Expected boolean setting")
            value = int(value)
        elif field == "warn_limit":
            if type(value) is not int or not 1 <= value <= 10:
                raise ValueError("warn_limit must be 1..10")
        elif field == "mention_limit":
            if type(value) is not int or not 3 <= value <= 15:
                raise ValueError("mention_limit must be 3..15")
        elif field == "rules":
            if type(value) is not str or not 3 <= len(value) <= 1200:
                raise ValueError("rules must be 3..1200 chars")
        elif field == "welcome_text":
            if type(value) is not str or len(value) > 500:
                raise ValueError("welcome_text too long")
        current = self.get_chat(chat_id)
        old = current[field]
        if old != value:
            self.conn.execute(f"UPDATE chats SET {field}=? WHERE chat_id=?", (value,chat_id))
            self.conn.execute("INSERT INTO setting_audit(chat_id,actor_id,field,old_value,new_value,created) VALUES(?,?,?,?,?,?)",
                              (chat_id,actor_id,field,str(old)[:120],str(value)[:120],int(time.time())))
        return self.get_chat(chat_id)

    def track(self, chat_id: int, key: str, amount: int = 1, now: int | None = None) -> None:
        if key not in {"messages", "joins", "actions"} or not 0 < amount <= 50:
            raise ValueError("Invalid activity metric")
        day = datetime.fromtimestamp(int(time.time() if now is None else now), timezone.utc).date().isoformat()
        self.conn.execute(f"INSERT INTO daily_activity(chat_id,day,{key}) VALUES(?,?,?) ON CONFLICT(chat_id,day) DO UPDATE SET {key}={key}+excluded.{key}",
                          (chat_id,day,amount))

    def timeline(self, chat_id: int, days: int = 14) -> list[dict]:
        days = max(1,min(int(days),31))
        today = datetime.now(timezone.utc).date()
        rows = {r['day']: dict(r) for r in self.conn.execute("SELECT day,messages,joins,actions FROM daily_activity WHERE chat_id=? AND day>=?",
                   (chat_id,(today-timedelta(days=days-1)).isoformat()))}
        return [rows.get((today-timedelta(days=i)).isoformat(),
                {"day":(today-timedelta(days=i)).isoformat(), "messages":0,"joins":0,"actions":0})
                for i in range(days-1,-1,-1)]

    def record_audit(self, chat_id: int, actor_id: int, field: str, old: str, new: str) -> None:
        self.conn.execute("INSERT INTO setting_audit(chat_id,actor_id,field,old_value,new_value,created) VALUES(?,?,?,?,?,?)",
                          (chat_id,actor_id,field[:60],old[:120],new[:120],int(time.time())))

    def audit(self, chat_id: int, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM setting_audit WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                  (chat_id,max(1,min(limit,50))))]

    def known_chats(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT chat_id,title FROM chats WHERE chat_id < 0 ORDER BY created_at DESC LIMIT ?",(min(limit,100),))]

    def known_chat(self, chat_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM chats WHERE chat_id=?",(chat_id,)).fetchone()
        return dict(row) if row else None

    def set_rules(self, chat_id: int, rules: str) -> None:
        self.ensure_chat(chat_id)
        self.conn.execute("UPDATE chats SET rules=? WHERE chat_id=?", (rules[:1200], chat_id))

    def list_words(self, chat_id: int) -> list[str]:
        return [row[0] for row in self.conn.execute("SELECT word FROM bad_words WHERE chat_id=? ORDER BY word LIMIT 100", (chat_id,))]

    def add_word(self, chat_id: int, word: str) -> bool:
        if len(self.list_words(chat_id)) >= 100:
            return False
        cur = self.conn.execute("INSERT OR IGNORE INTO bad_words(chat_id, word) VALUES(?, ?)", (chat_id, word))
        return bool(cur.rowcount)

    def remove_word(self, chat_id: int, word: str) -> bool:
        cur = self.conn.execute("DELETE FROM bad_words WHERE chat_id=? AND word=?", (chat_id, word))
        return bool(cur.rowcount)

    def ensure_member(self, chat_id: int, user_id: int, name: str = "") -> None:
        self.conn.execute("INSERT OR IGNORE INTO members(chat_id, user_id, name) VALUES (?, ?, ?)", (chat_id, user_id, name[:100]))
        if name:
            self.conn.execute("UPDATE members SET name=? WHERE chat_id=? AND user_id=?", (name[:100], chat_id, user_id))

    def activity(self, chat_id: int, user_id: int, name: str, now: int | None = None, enabled: bool = True) -> bool:
        now = int(now if now is not None else time.time())
        self.ensure_member(chat_id, user_id, name)
        self.conn.execute("UPDATE members SET messages=messages+1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        self.track(chat_id, "messages", now=now)
        if not enabled:
            return False
        cur = self.conn.execute("UPDATE members SET xp=xp+?, last_xp=? WHERE chat_id=? AND user_id=? AND last_xp <= ?",
                                (random.randint(6, 12), now, chat_id, user_id, now-60))
        earned = bool(cur.rowcount)
        if earned:
            day = datetime.fromtimestamp(now,timezone.utc).date().isoformat()
            self.conn.execute("""INSERT INTO member_day(chat_id,user_id,day,messages) VALUES(?,?,?,1)
              ON CONFLICT(chat_id,user_id,day) DO UPDATE SET messages=messages+1""",(chat_id,user_id,day))
        return earned

    def profile(self, chat_id: int, user_id: int, name: str = "") -> dict:
        self.ensure_member(chat_id, user_id, name)
        return dict(self.conn.execute("SELECT * FROM members WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone())

    def mission(self, chat_id: int, user_id: int, day: str | None = None) -> dict:
        day = day or datetime.now(timezone.utc).date().isoformat()
        row=self.conn.execute("SELECT messages,claimed FROM member_day WHERE chat_id=? AND user_id=? AND day=?",
                              (chat_id,user_id,day)).fetchone()
        return {"messages":row["messages"] if row else 0,"claimed":bool(row["claimed"]) if row else False,
                "goal":5,"reward":35,"day":day}

    def claim_mission(self, chat_id: int, user_id: int, day: str | None = None) -> str:
        day = day or datetime.now(timezone.utc).date().isoformat()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row=self.conn.execute("SELECT messages,claimed FROM member_day WHERE chat_id=? AND user_id=? AND day=?",
                                  (chat_id,user_id,day)).fetchone()
            if not row or row["messages"] < 5:
                result="not_ready"
            elif row["claimed"]:
                result="already"
            else:
                self.conn.execute("UPDATE member_day SET claimed=1 WHERE chat_id=? AND user_id=? AND day=?",
                                  (chat_id,user_id,day))
                self.ensure_member(chat_id,user_id)
                self.conn.execute("UPDATE members SET coins=coins+35 WHERE chat_id=? AND user_id=?",
                                  (chat_id,user_id))
                result="claimed"
            self.conn.execute("COMMIT")
            return result
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def give_thanks(self, chat_id: int, giver: int, receiver: int, day: str | None = None) -> bool:
        if giver <= 0 or receiver <= 0 or giver == receiver:
            return False
        day = day or datetime.now(timezone.utc).date().isoformat()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            result=self.conn.execute("INSERT OR IGNORE INTO kudos(chat_id,giver_id,day,receiver_id) VALUES(?,?,?,?)",
                                     (chat_id,giver,day,receiver))
            if result.rowcount:
                self.ensure_member(chat_id,receiver)
                self.conn.execute("UPDATE members SET reputation=reputation+1 WHERE chat_id=? AND user_id=?",
                                  (chat_id,receiver))
            self.conn.execute("COMMIT")
            return bool(result.rowcount)
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def community(self, chat_id: int) -> dict:
        today = datetime.now(timezone.utc).date().isoformat()
        daily=self.conn.execute("SELECT COUNT(*) AS active, SUM(claimed) AS claimed FROM member_day WHERE chat_id=? AND day=?",
                                (chat_id,today)).fetchone()
        kudos=self.conn.execute("SELECT COUNT(*) FROM kudos WHERE chat_id=? AND day=?",(chat_id,today)).fetchone()[0]
        leaders=[dict(r) for r in self.conn.execute("""SELECT user_id,name,reputation FROM members
               WHERE chat_id=? AND reputation>0 ORDER BY reputation DESC, user_id ASC LIMIT 10""",(chat_id,))]
        return {"active_today":daily["active"] or 0,"claimed_today":daily["claimed"] or 0,
                "thanks_today":kudos,"top_reputation":leaders,"mission_goal":5,"mission_reward":35}

    def top(self, chat_id: int, limit: int = 10) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM members WHERE chat_id=? AND messages>0 ORDER BY xp DESC, messages DESC LIMIT ?", (chat_id, limit))
        return [dict(x) for x in rows]

    def daily(self, chat_id: int, user_id: int, name: str, amount: int, day: str | None = None) -> tuple[bool, int]:
        day = day or datetime.now(timezone.utc).strftime('%Y-%m-%d')
        self.ensure_member(chat_id, user_id, name)
        yesterday = (datetime.fromisoformat(day).date() - timedelta(days=1)).isoformat()
        cur = self.conn.execute("""UPDATE members SET last_daily=?, coins=coins+?,
                             daily_streak=CASE WHEN last_daily=? THEN daily_streak+1 ELSE 1 END
                             WHERE chat_id=? AND user_id=? AND last_daily!=?""",
                                (day, amount, yesterday, chat_id, user_id, day))
        coins = self.profile(chat_id, user_id)["coins"]
        return (bool(cur.rowcount), coins)

    def add_coins(self, chat_id: int, user_id: int, amount: int) -> None:
        self.ensure_member(chat_id, user_id)
        self.conn.execute("UPDATE members SET coins=coins+? WHERE chat_id=? AND user_id=?", (amount, chat_id, user_id))

    def buy_badge(self, chat_id: int, user_id: int, badge: str, price: int) -> str:
        """Buy once with earned coins; previously purchased badges can be equipped free."""
        if not badge or price < 0:
            raise ValueError("Invalid badge")
        self.ensure_member(chat_id, user_id)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            owned = self.conn.execute("SELECT 1 FROM owned_badges WHERE chat_id=? AND user_id=? AND badge=?",
                                      (chat_id, user_id, badge)).fetchone()
            if owned:
                self.conn.execute("UPDATE members SET active_badge=? WHERE chat_id=? AND user_id=?",
                                  (badge, chat_id, user_id))
                result = "equipped"
            else:
                cur = self.conn.execute("UPDATE members SET coins=coins-?, active_badge=? WHERE chat_id=? AND user_id=? AND coins>=?",
                                        (price, badge, chat_id, user_id, price))
                if cur.rowcount:
                    self.conn.execute("INSERT INTO owned_badges(chat_id,user_id,badge) VALUES (?,?,?)",
                                      (chat_id, user_id, badge))
                    result = "purchased"
                else:
                    result = "insufficient"
            self.conn.execute("COMMIT")
            return result
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def owned_badges(self, chat_id: int, user_id: int) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT badge FROM owned_badges WHERE chat_id=? AND user_id=?", (chat_id, user_id))]

    def warn(self, chat_id: int, user_id: int) -> int:
        self.conn.execute("INSERT OR IGNORE INTO warnings(chat_id,user_id) VALUES (?, ?)", (chat_id, user_id))
        self.conn.execute("UPDATE warnings SET count=count+1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return self.get_warn(chat_id, user_id)

    def get_warn(self, chat_id: int, user_id: int) -> int:
        item = self.conn.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return item[0] if item else 0

    def un_warn(self, chat_id: int, user_id: int) -> int:
        self.conn.execute("UPDATE warnings SET count=max(0,count-1) WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return self.get_warn(chat_id, user_id)

    def reset_warn(self, chat_id: int, user_id: int) -> None:
        self.conn.execute("UPDATE warnings SET count=0 WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    def log_action(self, chat_id: int, admin_id: int | None, target_id: int, action: str, reason: str = "") -> None:
        self.conn.execute("INSERT INTO modlog(chat_id, admin_id, target_id, action, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                          (chat_id, admin_id, target_id, action, reason[:160], int(time.time())))
        self.track(chat_id,"actions")

    def recent_actions(self, chat_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM modlog WHERE chat_id=? ORDER BY id DESC LIMIT 8", (chat_id,))]

    def new_quiz(self, chat_id: int, correct: int, ttl_seconds: int = 180) -> int | None:
        now = int(time.time())
        last = self.conn.execute("SELECT created FROM quizzes WHERE chat_id=? ORDER BY quiz_id DESC LIMIT 1", (chat_id,)).fetchone()
        if last and now-last[0] < 45:
            return None
        cur = self.conn.execute("INSERT INTO quizzes(chat_id,correct,expires,created) VALUES (?,?,?,?)",
                                (chat_id, correct, now+ttl_seconds, now))
        return int(cur.lastrowid)

    def answer_quiz(self, quiz_id: int, chat_id: int, user_id: int, option: int) -> str:
        quiz = self.conn.execute("SELECT * FROM quizzes WHERE quiz_id=? AND chat_id=?", (quiz_id, chat_id)).fetchone()
        if not quiz:
            return "not_found"
        if int(time.time()) >= quiz["expires"]:
            return "expired"
        answer = self.conn.execute("SELECT correct FROM quiz_answers WHERE quiz_id=? AND user_id=?", (quiz_id,user_id)).fetchone()
        if answer:
            return "already"
        result = "correct" if option == quiz["correct"] else "wrong"
        self.conn.execute("INSERT INTO quiz_answers(quiz_id,user_id,correct) VALUES(?,?,?)", (quiz_id,user_id,int(result == "correct")))
        if result == "correct":
            self.add_coins(chat_id,user_id,15)
        return result

    # 0.2.0 — settings, anti-raid, captcha, reports and rock-paper-scissors.
    def set_warn_limit(self, chat_id: int, limit: int) -> None:
        if not 1 <= limit <= 10:
            raise ValueError("Порог предупреждений: 1–10")
        self.ensure_chat(chat_id)
        self.conn.execute("UPDATE chats SET warn_limit=? WHERE chat_id=?", (limit, chat_id))

    def set_welcome_text(self, chat_id: int, template: str) -> None:
        if len(template) > 500:
            raise ValueError("Длина приветствия — до 500 символов")
        self.ensure_chat(chat_id)
        self.conn.execute("UPDATE chats SET welcome_text=? WHERE chat_id=?", (template, chat_id))

    def raid(self, chat_id: int, until: int) -> None:
        self.ensure_chat(chat_id)
        self.conn.execute("UPDATE chats SET raid_until=? WHERE chat_id=?", (until, chat_id))

    def list_domains(self, chat_id: int) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT domain FROM allowed_domains WHERE chat_id=? ORDER BY domain LIMIT 100", (chat_id,))]

    def add_domain(self, chat_id: int, domain: str) -> bool:
        if len(self.list_domains(chat_id)) >= 100:
            return False
        return bool(self.conn.execute("INSERT OR IGNORE INTO allowed_domains VALUES (?,?)", (chat_id, domain)).rowcount)

    def remove_domain(self, chat_id: int, domain: str) -> bool:
        return bool(self.conn.execute("DELETE FROM allowed_domains WHERE chat_id=? AND domain=?", (chat_id, domain)).rowcount)

    def new_challenge(self, chat_id: int, user_id: int, question: str, correct: int,
                      options: str, expires: int) -> None:
        self.conn.execute("""INSERT INTO challenges(chat_id,user_id,question,correct,options,expires)
                VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
                question=excluded.question,correct=excluded.correct,options=excluded.options,
                expires=excluded.expires,attempts=0,message_id=0""",
                (chat_id, user_id, question, correct, options, expires))

    def set_challenge_message(self, chat_id: int, user_id: int, message_id: int) -> None:
        self.conn.execute("UPDATE challenges SET message_id=? WHERE chat_id=? AND user_id=?", (message_id, chat_id, user_id))

    def challenge(self, chat_id: int, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM challenges WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return dict(row) if row else None

    def attempt_challenge(self, chat_id: int, user_id: int, option: int, now: int | None = None) -> str:
        now = int(time.time()) if now is None else now
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT * FROM challenges WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            if not row:
                result = "missing"
            elif row["expires"] <= now:
                result = "expired"
            elif option == row["correct"]:
                result = "correct"  # Do not delete until Telegram unrestrict succeeds.
            else:
                self.conn.execute("UPDATE challenges SET attempts=attempts+1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
                result = "wrong"
            self.conn.execute("COMMIT")
            return result
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def delete_challenge(self, chat_id: int, user_id: int) -> None:
        self.conn.execute("DELETE FROM challenges WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    def expired_challenges(self, now: int | None = None, limit: int = 20) -> list[dict]:
        now = int(time.time()) if now is None else now
        return [dict(r) for r in self.conn.execute("SELECT * FROM challenges WHERE expires<=? ORDER BY expires LIMIT ?", (now, limit))]

    def report(self, chat_id: int, reporter_id: int, target_id: int, message_id: int,
               now: int | None = None) -> str:
        now = int(time.time()) if now is None else now
        # At most 3 reports from a participant in any rolling hour. Duplicate ID is checked first.
        old = self.conn.execute("SELECT id FROM reports WHERE chat_id=? AND reporter_id=? AND target_message_id=?",
                                (chat_id, reporter_id, message_id)).fetchone()
        if old:
            return "duplicate"
        count = self.conn.execute("SELECT COUNT(*) FROM reports WHERE chat_id=? AND reporter_id=? AND created>?",
                                  (chat_id, reporter_id, now-3600)).fetchone()[0]
        if count >= 3:
            return "limited"
        self.conn.execute("INSERT INTO reports(chat_id,reporter_id,target_id,target_message_id,created) VALUES (?,?,?,?,?)",
                          (chat_id, reporter_id, target_id, message_id, now))
        return "created"

    def reports(self, chat_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM reports WHERE chat_id=? AND status='open' ORDER BY id DESC LIMIT 10", (chat_id,))]

    def report_history(self, chat_id: int, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM reports WHERE chat_id=? AND status!='open' ORDER BY resolved_at DESC,id DESC LIMIT ?",
            (chat_id, max(1, min(int(limit), 50))))]

    def user_reports(self, user_id: int, limit: int = 10) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT r.id,r.chat_id,c.title,r.created,r.status,r.decision_reason,r.resolved_at,r.notification_status "
            "FROM reports r LEFT JOIN chats c ON c.chat_id=r.chat_id "
            "WHERE r.reporter_id=? ORDER BY r.id DESC LIMIT ?", (user_id, max(1, min(limit, 30))))]

    def register_private(self, user_id: int, *, enabled: bool | None = None) -> None:
        now = int(time.time())
        self.conn.execute("INSERT OR IGNORE INTO private_users(user_id,started_at,updated_at) VALUES(?,?,?)",
                          (user_id,now,now))
        if enabled is not None:
            self.conn.execute("UPDATE private_users SET notifications_enabled=?,updated_at=? WHERE user_id=?",
                              (int(enabled),now,user_id))

    def set_news_enabled(self, user_id: int, enabled: bool) -> bool:
        """Subscribe only a user who has already started the private chat."""
        row = self.conn.execute("SELECT user_id FROM private_users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return False
        self.conn.execute("UPDATE private_users SET news_enabled=?,updated_at=? WHERE user_id=?",
                          (int(enabled), int(time.time()), user_id))
        return True

    def news_enabled(self, user_id: int) -> bool:
        row = self.conn.execute("SELECT news_enabled FROM private_users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row[0])

    def stage_news_release(self, version: str, text: str, now: int | None = None) -> int:
        """Idempotently enroll existing opt-in users, not future subscribers."""
        if not version or len(version) > 64 or not text or len(text) > 3900:
            raise ValueError("Invalid release announcement")
        now = int(time.time()) if now is None else int(now)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute("INSERT OR IGNORE INTO news_releases(version,text,created) VALUES(?,?,?)",
                                       (version, text, now))
            # Snapshot recipients exactly once per release. Later opt-ins do not get old news.
            if cursor.rowcount:
                self.conn.execute("""
                    INSERT OR IGNORE INTO news_deliveries(version,user_id)
                    SELECT ?,user_id FROM private_users WHERE news_enabled=1
                """, (version,))
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        row = self.conn.execute("SELECT count(*) FROM news_deliveries WHERE version=?", (version,)).fetchone()
        return int(row[0])

    def has_news_work(self, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        return bool(self.conn.execute("""
            SELECT 1 FROM news_deliveries d
            JOIN private_users p ON d.user_id=p.user_id
            WHERE d.status='pending' AND d.retry_at<=? AND p.news_enabled=1 LIMIT 1
        """, (now,)).fetchone())

    def claim_news_delivery(self, now: int | None = None) -> dict | None:
        """Claim-before-send: avoids duplicate news after crash (may skip uncertain sends)."""
        now = int(time.time()) if now is None else int(now)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            item = self.conn.execute("""
                SELECT d.version,d.user_id,d.attempts,r.text
                FROM news_deliveries d JOIN news_releases r ON d.version=r.version
                JOIN private_users p ON p.user_id=d.user_id
                WHERE d.status='pending' AND d.retry_at<=? AND p.news_enabled=1
                ORDER BY r.created,d.user_id LIMIT 1
            """, (now,)).fetchone()
            if item:
                self.conn.execute("""
                    UPDATE news_deliveries SET status='sending', attempts=attempts+1
                    WHERE version=? AND user_id=? AND status='pending'
                """, (item['version'], item['user_id']))
            self.conn.execute("COMMIT")
            return dict(item) if item else None
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def finish_news_delivery(self, version: str, user_id: int, status: str,
                             *, retry_after: int = 0, now: int | None = None) -> None:
        if status not in {'sent','pending','failed','uncertain'}:
            raise ValueError("Invalid news delivery state")
        now = int(time.time()) if now is None else int(now)
        self.conn.execute("""
            UPDATE news_deliveries SET status=?,retry_at=?,delivered_at=?
            WHERE version=? AND user_id=? AND status='sending'
        """, (status, now + max(1, retry_after) if status == 'pending' else 0,
              now if status == 'sent' else 0, version, user_id))

    def news_stats(self, version: str) -> dict:
        return {row['status']: row['n'] for row in self.conn.execute(
            'SELECT status, count(*) n FROM news_deliveries WHERE version=? GROUP BY status', (version,))}

    def notifications_allowed(self, user_id: int) -> bool:
        row=self.conn.execute("SELECT notifications_enabled FROM private_users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row[0])

    def record_delivery(self, report_id: int, chat_id: int, status: str) -> None:
        if status not in {"sent", "not_started", "failed", "disabled"}:
            raise ValueError("Invalid delivery status")
        self.conn.execute("UPDATE reports SET notification_status=?,notified_at=? WHERE id=? AND chat_id=?",
                          (status,int(time.time()) if status=="sent" else 0,report_id,chat_id))

    def record_target_delivery(self, report_id: int, chat_id: int, status: str) -> None:
        if status not in {"sent", "not_started", "failed", "disabled"}:
            raise ValueError("Invalid target delivery status")
        self.conn.execute("UPDATE reports SET target_notification_status=? WHERE id=? AND chat_id=?",
                          (status,report_id,chat_id))

    def decide_report(self, report_id: int, chat_id: int, admin_id: int, action: str, reason: str) -> bool:
        if action not in {"rejected", "warned", "closed"}:
            raise ValueError("Invalid decision")
        if not isinstance(reason,str):
            raise ValueError("Reason must be text")
        reason=reason.strip()
        if (action=="rejected" and not 5<=len(reason)<=300) or (action!="rejected" and not 1<=len(reason)<=300):
            raise ValueError("Reason must be 5–300 characters for rejection or 1–300 for other decisions")
        result=self.conn.execute(
            "UPDATE reports SET status=?,resolved_by=?,decision_reason=?,resolved_at=? "
            "WHERE id=? AND chat_id=? AND status='open'",
            (action,admin_id,reason,int(time.time()),report_id,chat_id))
        if result.rowcount:
            self.record_audit(chat_id, admin_id, "report_"+action, str(report_id), reason[:120])
        return bool(result.rowcount)

    def get_report(self, report_id: int, chat_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM reports WHERE id=? AND chat_id=?", (report_id, chat_id)).fetchone()
        return dict(row) if row else None

    def resolve_report(self, report_id: int, chat_id: int, admin_id: int) -> bool:
        """Legacy explicit close, retained for old callback/test compatibility.
        New rejection path requires moderator-entered reason.
        """
        return self.decide_report(report_id,chat_id,admin_id,"closed","Закрыта модератором без санкций")

    def stats(self, chat_id: int) -> dict:
        def count(query):
            return self.conn.execute(query, (chat_id,)).fetchone()[0]
        return {
            "members": count("SELECT COUNT(*) FROM members WHERE chat_id=?"),
            "messages": count("SELECT COALESCE(SUM(messages),0) FROM members WHERE chat_id=?"),
            "warnings": count("SELECT COALESCE(SUM(count),0) FROM warnings WHERE chat_id=?"),
            "reports": count("SELECT COUNT(*) FROM reports WHERE chat_id=? AND status='open'"),
            "actions": count("SELECT COUNT(*) FROM modlog WHERE chat_id=?"),
        }

    def create_rps(self, chat_id: int, user_id: int, bot_choice: int, expires: int) -> int:
        cur = self.conn.execute("INSERT INTO rps_games(chat_id,user_id,bot_choice,expires) VALUES (?,?,?,?)",
                                (chat_id,user_id,bot_choice,expires))
        return int(cur.lastrowid)

    def play_rps(self, game_id: int, chat_id: int, user_id: int, choice: int, now: int | None = None) -> str:
        now = int(time.time()) if now is None else now
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT * FROM rps_games WHERE id=? AND chat_id=? AND user_id=?", (game_id,chat_id,user_id)).fetchone()
            if not row: result = "not_yours"
            elif row["settled"]: result = "already"
            elif row["expires"] <= now: result = "expired"
            elif choice not in (0,1,2): result = "invalid"
            else:
                bot = row["bot_choice"]
                result = "draw" if choice == bot else ("win" if (choice-bot)%3 == 2 else "lose")
                self.conn.execute("UPDATE rps_games SET settled=1 WHERE id=?", (game_id,))
                if result == "win":
                    self.add_coins(chat_id, user_id, 8)
            self.conn.execute("COMMIT")
            return result
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
