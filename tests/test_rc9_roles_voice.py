"""RC9: native member tags, role permissions, opt-in speech, Mini App security."""
from __future__ import annotations
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from krew.api import TelegramError
from krew.core import BotCore
from krew.db import Database
from krew.roles import clean_tag
from krew.speech import SpeechError, transcribe_voice, MAX_VOICE_BYTES
from krew.web import Application


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.reject_tag = False

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "getChatMember":
            uid = params.get("user_id")
            if uid == 1:
                return {"status": "creator", "user": {"id": 1, "first_name": "Владелец"}}
            if uid == 2:
                return {"status": "administrator", "can_be_edited": True,
                        "user": {"id": 2, "first_name": "Модератор"}}
            if uid == 9:
                return {"status": "left", "user": {"id": 9}}
            return {"status": "member", "user": {"id": uid, "first_name": "Гость"}}
        if method == "setChatMemberTag" and self.reject_tag:
            raise TelegramError("insufficient rights", 403)
        if method in ("sendMessage", "sendRichMessage", "editMessageText"):
            return {"message_id": 42}
        return True


class RolesAndSpeechTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "krew.sqlite3"
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.api = FakeAPI()
        self.bot = BotCore(self.api, self.db, "krew_test")

    def msg(self, text: str, actor=1, replied=5, private=False, voice=None):
        source = {"chat": {"id": 17 if private else -100,
                           "type": "private" if private else "supergroup",
                           "title": "Test"}, "from": {"id": actor, "first_name": "User"},
                  "message_id": 80, "text": text}
        if replied:
            source["reply_to_message"] = {
                "message_id": 79, "from": {"id": replied, "first_name": "Гость"}}
            if voice is not None:
                source["reply_to_message"]["voice"] = voice
        return source

    def test_valid_tags_and_reserved_titles(self):
        self.assertEqual(clean_tag("  VIP  "), "VIP")
        self.assertEqual(clean_tag(" Старший  помощник "), "Старший помощник")
        for tag in ("", "🚀", "Admin", "Модератор", "<b>VIP</b>", "x" * 17):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                clean_tag(tag)

    def test_native_role_tag_is_written_only_after_telegram_success(self):
        self.bot.on_message(self.msg("/role Активист"))
        self.assertIn(("setChatMemberTag", {"chat_id": -100, "user_id": 5,
                                           "tag": "Активист"}), self.api.calls)
        self.assertEqual(self.db.role_tag(-100, 5), "Активист")
        self.assertEqual(self.db.role_tags(-100)[0]["name"], "Гость")

    def test_role_assignment_never_grants_administrator_rights(self):
        self.bot.on_message(self.msg("/role Помощник"))
        methods = [name for name, _ in self.api.calls]
        self.assertNotIn("promoteChatMember", methods)
        self.assertNotIn("restrictChatMember", methods)

    def test_non_admin_cannot_assign(self):
        self.bot.on_message(self.msg("/role VIP", actor=5, replied=6))
        self.assertFalse(any(name == "setChatMemberTag" for name, _ in self.api.calls))
        self.assertEqual(self.db.role_tag(-100, 6), "")

    def test_telegram_failure_leaves_database_unchanged(self):
        self.api.reject_tag = True
        self.bot.on_message(self.msg("/role VIP"))
        self.assertEqual(self.db.role_tag(-100, 5), "")

    def test_cannot_assign_regular_tag_to_existing_admin(self):
        self.bot.on_message(self.msg("/role VIP", actor=1, replied=2))
        self.assertFalse(any(name == "setChatMemberTag" for name, _ in self.api.calls))

    def test_unrole_clears_visible_tag_and_database(self):
        self.bot.on_message(self.msg("/role VIP"))
        self.bot.on_message(self.msg("/unrole"))
        self.assertEqual(self.db.role_tag(-100, 5), "")
        self.assertEqual(self.api.calls[-2][0], "setChatMemberTag")

    def test_roles_survive_database_reopen(self):
        self.db.set_role_tag(-100, 5, "Ветеран", 1, "Гость")
        self.db.close()
        reopened = Database(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.role_tag(-100, 5), "Ветеран")

    def test_public_commands_display_saved_tag(self):
        self.db.set_role_tag(-100, 5, "VIP", 1, "Гость")
        self.bot.on_message(self.msg("/whois", actor=5, replied=0))
        self.assertIn("VIP", str(self.api.calls[-1][1]))
        self.bot.on_message(self.msg("/myrole", actor=5, replied=0))
        self.assertIn("VIP", self.api.calls[-1][1]["text"])
        self.bot.on_message(self.msg("/roles", actor=5, replied=0))
        self.assertIn("VIP", self.api.calls[-1][1]["text"])

    def test_modcenter_is_admin_only(self):
        self.bot.on_message(self.msg("/modcenter", actor=5))
        self.assertIn("администраторам", self.api.calls[-1][1]["text"])
        self.bot.on_message(self.msg("/modcenter", actor=1))
        self.assertIn("Центр модерации", self.api.calls[-1][1]["text"])

    def test_admintitle_owner_only_and_permissions_unchanged(self):
        self.bot.on_message(self.msg("/admintitle Куратор", actor=2, replied=5))
        self.assertNotIn("setChatAdministratorCustomTitle", [name for name, _ in self.api.calls])
        self.bot.on_message(self.msg("/admintitle Куратор", actor=1, replied=2))
        self.assertIn("setChatAdministratorCustomTitle", [name for name, _ in self.api.calls])
        self.assertNotIn("promoteChatMember", [name for name, _ in self.api.calls])

    def test_voice_requires_explicit_provider_setup(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "test:token", "GROQ_API_KEY": ""}):
            self.bot.on_message(self.msg("/transcribe", actor=5, replied=5,
                 voice={"file_id": "file1", "duration": 3, "file_size": 500}))
        self.assertIn("GROQ_API_KEY", self.api.calls[-1][1]["text"])
        self.assertFalse(any(name == "getFile" for name, _ in self.api.calls))

    def test_voice_of_other_people_rejected_before_network(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "test:token", "GROQ_API_KEY": "test-key"}):
            self.bot.on_message(self.msg("/transcribe", actor=5, replied=6,
                voice={"file_id": "file1", "duration": 3, "file_size": 500}))
        self.assertIn("собственные", self.api.calls[-1][1]["text"])
        self.assertFalse(any(name == "getFile" for name, _ in self.api.calls))

    def test_voice_length_limit_and_daily_quota(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "test:token", "GROQ_API_KEY": "test-key"}):
            self.bot.on_message(self.msg("/transcribe", actor=5, replied=5,
                voice={"file_id": "file1", "duration": 180, "file_size": 500}))
        self.assertIn("Лимит", self.api.calls[-1][1]["text"])
        self.assertEqual(self.db.remaining_voice_requests(-100, 5), 3)
        self.assertTrue(self.db.reserve_voice_request(-100, 5))
        self.assertTrue(self.db.reserve_voice_request(-100, 5))
        self.assertTrue(self.db.reserve_voice_request(-100, 5))
        self.assertFalse(self.db.reserve_voice_request(-100, 5))
        self.assertEqual(self.db.remaining_voice_requests(-100, 5), 0)

    def test_voice_worker_is_nonblocking(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "test:token", "GROQ_API_KEY": "test-key"}), \
             patch("krew.core.threading.Thread") as worker:
            self.bot.on_message(self.msg("/transcribe", actor=5, replied=5,
                voice={"file_id": "file1", "duration": 3, "file_size": 500}))
            worker.assert_called_once()
            worker.return_value.start.assert_called_once()
        self.assertIn("Распознаю", self.api.calls[-1][1]["text"])

    def test_speech_file_path_rejects_traversal(self):
        api = Mock()
        api.call.return_value = {"file_path": "../escape.ogg", "file_size": 3}
        with self.assertRaises(SpeechError), patch("krew.speech.urlopen") as download:
            transcribe_voice(api, "test:token", "test-key", "file1")
        download.assert_not_called()

    def test_speech_rejects_large_telegram_voice_without_downloading(self):
        api = Mock()
        api.call.return_value = {"file_path": "voice/a.oga",
                                 "file_size": MAX_VOICE_BYTES + 1}
        with self.assertRaises(SpeechError), patch("krew.speech.urlopen") as download:
            transcribe_voice(api, "test:token", "test-key", "file1")
        download.assert_not_called()

    def test_speech_multipart_request_has_correct_provider(self):
        api = Mock()
        api.call.return_value = {"file_path": "voice/a.oga", "file_size": 6}
        def opened(request, timeout):
            url = request.full_url
            if "api.telegram.org/file/" in url:
                return io.BytesIO(b"oggdata")
            self.assertEqual(url, "https://api.groq.com/openai/v1/audio/transcriptions")
            self.assertIn(b"whisper-large-v3-turbo", request.data)
            self.assertIn(b"oggdata", request.data)
            return io.BytesIO(json.dumps({"text": "Привет, KREW!"}).encode("utf-8"))
        with patch("krew.speech.urlopen", side_effect=opened):
            result = transcribe_voice(api, "test:token", "test-key", "file1")
        self.assertEqual(result, "Привет, KREW!")

    def test_mini_app_roles_authorized_and_validated(self):
        self.db.ensure_chat(-100, "Test")
        app = Application("test:token", self.path, self.api)
        with patch.object(app, "user", return_value={"id": 1}):
            status, body = app.process("POST", "/api/chats/-100/roles", "", {
                "user_id": 5, "tag": "VIP"})
            self.assertEqual(status, 200)
            self.assertEqual(body["roles"][0]["tag"], "VIP")
            self.assertEqual(self.db.role_tag(-100, 5), "VIP")
            status, _ = app.process("POST", "/api/chats/-100/roles", "", {
                "user_id": 5, "tag": "🚀 VIP"})
            self.assertEqual(status, 400)
            self.assertEqual(self.db.role_tag(-100, 5), "VIP")
            status, _ = app.process("POST", "/api/chats/-100/roles", "", {
                "user_id": 2, "tag": "VIP"})
            self.assertEqual(status, 409)

    def test_mini_app_nonadmin_cannot_edit_roles(self):
        self.db.ensure_chat(-100, "Test")
        app = Application("test:token", self.path, self.api)
        with patch.object(app, "user", return_value={"id": 5}):
            status, _ = app.process("POST", "/api/chats/-100/roles", "", {
                "user_id": 6, "tag": "VIP"})
        self.assertEqual(status, 403)
        self.assertEqual(self.db.role_tag(-100, 6), "")


if __name__ == "__main__":
    unittest.main()
