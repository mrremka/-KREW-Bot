"""Launch-time status and pinned messages commands."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from krew.api import TelegramError
from krew.core import BotCore, installed_version
from krew.db import Database

class Stub:
    def __init__(self):
        self.calls = []
        self.fail_pin = False

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'getChatMember':
            return {'status': 'administrator' if params['user_id'] == 1 else 'member'}
        if method in ('pinChatMessage', 'unpinChatMessage') and self.fail_pin:
            raise TelegramError('Forbidden', 403)
        if method == 'sendMessage':
            return {'message_id': 99}
        return True

class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name)/'test.sqlite3')
        self.addCleanup(self.db.close)
        self.api = Stub()
        self.bot = BotCore(self.api, self.db, 'krew_test')

    def group(self, uid, command, reply=None):
        msg = {'chat': {'id': -100, 'type': 'supergroup', 'title': 'Test'},
               'from': {'id': uid, 'first_name': 'User'},
               'message_id': 88, 'text': command}
        if reply is not None:
            msg['reply_to_message'] = {'message_id': reply, 'from': {'id': 5, 'first_name': 'Someone'}}
        self.bot.on_message(msg)

    def test_version_from_installed_file(self):
        self.assertEqual(installed_version(), '1.0.0-rc.8')
        self.group(5, '/version')
        self.assertIn('1.0.0-rc.8', self.api.calls[-1][1]['text'])

    def test_private_status_does_not_leak_secrets(self):
        with patch.dict('os.environ', {'WEBAPP_URL': 'https://example.com',
                                      'BOT_TOKEN': 'secret:123'}, clear=False):
            self.bot.on_message({'chat': {'id': 7, 'type': 'private'},
                                 'from': {'id': 7}, 'text': '/status', 'message_id': 3})
        msg = self.api.calls[-1][1]['text']
        self.assertIn('Подключена', msg)
        self.assertNotIn('secret:123', msg)
        self.assertNotIn('example.com', msg)

    def test_admin_status_is_gated(self):
        self.group(5, '/status')
        self.assertIn('только администраторам', self.api.calls[-1][1]['text'])
        self.group(1, '/status')
        self.assertIn('KREW · Статус', self.api.calls[-1][1]['rich_message']['html'])

    def test_regular_user_cannot_pin_or_unpin(self):
        self.group(5, '/pin', reply=91)
        self.group(5, '/unpin', reply=91)
        self.assertFalse(any(method in ('pinChatMessage', 'unpinChatMessage')
                             for method, _ in self.api.calls))

    def test_admin_pin_and_log(self):
        self.group(1, '/pin', reply=91)
        calls = [d for method, d in self.api.calls if method == 'pinChatMessage']
        self.assertEqual(calls, [{'chat_id': -100, 'message_id': 91, 'disable_notification': True}])
        self.assertEqual(self.db.recent_actions(-100)[0]['action'], 'pin')

    def test_pin_requires_reply(self):
        self.group(1, '/pin')
        self.assertFalse(any(method == 'pinChatMessage' for method, _ in self.api.calls))
        self.assertIn('Ответь /pin', self.api.calls[-1][1]['text'])

    def test_unpin_specific_and_latest(self):
        self.group(1, '/unpin', reply=91)
        self.group(1, '/unpin')
        calls = [d for method, d in self.api.calls if method == 'unpinChatMessage']
        self.assertEqual(calls, [{'chat_id': -100, 'message_id': 91}, {'chat_id': -100}])

    def test_failed_pin_does_not_log_success(self):
        self.api.fail_pin = True
        self.group(1, '/pin', reply=91)
        self.assertFalse(self.db.recent_actions(-100))
        self.assertIn('Не удалось выполнить', self.api.calls[-1][1]['text'])

if __name__ == '__main__':
    unittest.main()
