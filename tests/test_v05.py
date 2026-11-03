"""Shield+ protection, settings permissions and safe backup."""
import tempfile
import unittest
from pathlib import Path
from krew.db import Database
from krew.core import BotCore
from krew.rules import excessive_mentions, excessive_caps
from krew.web import Application
from backup import backup
from testsupport import DummyAPI, msg, signed_auth

class ShieldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        self.db = Database(self.path)
        self.db.ensure_chat(-100, 'Test')
        self.api = DummyAPI()
        self.core = BotCore(self.api, self.db, 'testbot')
        self.app = Application('test-token', self.path, self.api)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_new_settings_off_by_default_and_chat_scoped(self):
        self.assertEqual(self.db.get_chat(-100)['antimentions'], 0)
        self.assertEqual(self.db.get_chat(-100)['anticaps'], 0)
        self.assertEqual(self.db.get_chat(-100)['mention_limit'], 5)
        self.db.set_setting(-100, 'antimentions', True, 1)
        self.assertFalse(self.db.get_chat(-200)['antimentions'])
        self.assertEqual(len(self.db.audit(-100)), 1)

    def test_limits_are_strict(self):
        for v in (2, 16, True, '5', 0):
            with self.assertRaises(ValueError):
                self.db.set_setting(-100, 'mention_limit', v)
        self.db.set_setting(-100, 'mention_limit', 4)
        self.assertEqual(self.db.get_chat(-100)['mention_limit'], 4)

    def test_detect_mentions_but_not_email(self):
        self.assertTrue(excessive_mentions(' '.join(f'@person{i}' for i in range(5)), None, 5))
        self.assertFalse(excessive_mentions('contact name@example.com thanks', [], 3))
        self.assertTrue(excessive_mentions('hello', [{'type':'text_mention'}]*4, 4))

    def test_detect_long_caps_but_not_short_acronym(self):
        self.assertTrue(excessive_caps('ЭТО ОЧЕНЬ ДЛИННОЕ СООБЩЕНИЕ ТОЛЬКО В ВЕРХНЕМ РЕГИСТРЕ'))
        self.assertFalse(excessive_caps('CPU GPU HTTP'))
        self.assertFalse(excessive_caps('А вот это обычное содержательное сообщение'))

    def test_filter_deletes_and_warns(self):
        self.db.set_setting(-100, 'antimentions', True)
        self.core.on_message(msg(2, ' '.join(f'@person{i}' for i in range(5))))
        self.assertEqual(self.db.get_warn(-100, 2), 1)
        self.assertIn('deleteMessage', [m for m,_ in self.api.calls])

    def test_admin_not_punished(self):
        self.db.set_setting(-100, 'anticaps', True)
        self.core.on_message(msg(1, 'ЭТО ПОЛНОСТЬЮ ЗАГЛАВНОЕ ДЛИННОЕ СООБЩЕНИЕ ОТ АДМИНА'))
        self.assertNotIn('deleteMessage', [m for m,_ in self.api.calls])

    def test_admin_only_commands(self):
        self.core.on_message(msg(2, '/mentionlimit 3'))
        self.assertEqual(self.db.get_chat(-100)['mention_limit'], 5)
        self.core.on_message(msg(1, '/mentionlimit 3'))
        self.assertEqual(self.db.get_chat(-100)['mention_limit'], 3)

    def test_web_settings_protected(self):
        ep = '/api/chats/-100/settings'
        status, result = self.app.process('PATCH', ep, signed_auth('test-token', 1), {'field':'antimentions','value':True})
        self.assertEqual(status, 200)
        self.assertTrue(result['settings']['antimentions'])
        self.assertEqual(self.app.process('PATCH', ep, signed_auth('test-token', 2), {'field':'mention_limit','value':3})[0], 403)

    def test_backup_snapshot_is_integral_and_does_not_change_source(self):
        target=Path(self.tmp.name)/'backup.sqlite3'
        result=backup(self.path,target)
        self.assertEqual(result,target)
        check=Database(target)
        self.assertEqual(check.get_chat(-100)['title'],'Test')
        check.close()
        with self.assertRaises(FileExistsError):
            backup(self.path,target)
