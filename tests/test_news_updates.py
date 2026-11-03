import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from krew.db import Database
from krew.news import NewsBroadcaster,parse_release_notes
from krew.api import TelegramError
from krew.core import BotCore
from updater import parse_version, read_manifest, extract_verified_zip, UpdateError
import io, zipfile

ROOT=Path(__file__).resolve().parents[1]

class MockApi:
    def __init__(self, fail=None):
        self.sent=[]
        self.fail=fail
    def call(self, method, **kwargs):
        if method=='sendMessage':
            if self.fail:
                raise self.fail
            self.sent.append(kwargs)
            return {'message_id':len(self.sent)}
        return {}


class NewsletterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'test.sqlite3')
        self.addCleanup(self.db.close)
        self.api=MockApi()
        self.bot=BotCore(self.api,self.db,'testbot')

    def test_news_requires_start_and_explicit_optin(self):
        self.assertFalse(self.db.set_news_enabled(123,True))
        self.db.register_private(123)
        self.assertFalse(self.db.news_enabled(123))
        self.assertTrue(self.db.set_news_enabled(123,True))
        self.assertTrue(self.db.news_enabled(123))
        self.db.set_news_enabled(123,False)
        self.assertFalse(self.db.news_enabled(123))

    def test_private_commands_are_independent_of_report_notify(self):
        def incoming(cmd):
            self.bot.on_message({'chat':{'id':123,'type':'private'},'from':{'id':123},'text':cmd,'message_id':6})
        incoming('/start')
        incoming('/news on')
        self.assertTrue(self.db.news_enabled(123))
        incoming('/notify off')
        self.assertTrue(self.db.news_enabled(123))
        self.assertFalse(self.db.notifications_allowed(123))
        incoming('/news off')
        self.assertFalse(self.db.news_enabled(123))

    def test_optin_only_and_no_replay(self):
        self.db.register_private(11)
        self.db.register_private(12)
        self.db.set_news_enabled(11,True)
        self.db.stage_news_release('1.0.0','New feature',now=100)
        self.assertEqual(self.db.news_stats('1.0.0'),{'pending':1})
        broadcaster=NewsBroadcaster(self.api,self.db,ROOT)
        broadcaster.enabled=True
        self.assertEqual(broadcaster.tick(),'sent')
        self.assertEqual(len(self.api.sent),1)
        self.assertEqual(self.api.sent[0]['chat_id'],11)
        self.assertEqual(broadcaster.tick(),'idle')
        # Same release after restart cannot duplicate.
        self.db.stage_news_release('1.0.0','New feature',now=101)
        self.assertEqual(self.db.news_stats('1.0.0'),{'sent':1})
        self.db.set_news_enabled(12,True)
        self.db.stage_news_release('1.0.0','New feature',now=102)
        # This still enqueues user 12 on repeated stage, contrary to desired behavior.
        # We don't restage on restart for the first time after the release was created.
        self.assertEqual(self.db.news_stats('1.0.0'),{'sent':1})

    def test_disable_prevents_queued_send(self):
        self.db.register_private(11)
        self.db.set_news_enabled(11,True)
        self.db.stage_news_release('1.2.0','hello')
        self.db.set_news_enabled(11,False)
        self.assertFalse(self.db.has_news_work())
        announcer=NewsBroadcaster(self.api,self.db,ROOT); announcer.enabled=True
        self.assertEqual(announcer.tick(),'idle')

    def test_rate_limit_retry(self):
        self.db.register_private(11)
        self.db.set_news_enabled(11,True)
        self.db.stage_news_release('1.2.0','hello')
        announcer=NewsBroadcaster(MockApi(TelegramError('slow',429,1)),self.db,ROOT); announcer.enabled=True
        self.assertEqual(announcer.tick(),'rate_limited')
        self.assertEqual(self.db.news_stats('1.2.0'),{'pending':1})

    def test_blocked_user_unsubscribed(self):
        self.db.register_private(11)
        self.db.set_news_enabled(11,True)
        self.db.stage_news_release('1.2.0','hello')
        announcer=NewsBroadcaster(MockApi(TelegramError('blocked',403)),self.db,ROOT); announcer.enabled=True
        self.assertEqual(announcer.tick(),'failed')
        self.assertFalse(self.db.news_enabled(11))

    def test_release_notes_markup(self):
        version,message=parse_release_notes(ROOT)
        self.assertEqual(version,(ROOT/'VERSION').read_text(encoding='utf8').strip())
        self.assertIn('KREW',message)
        self.assertIn('/news off',message)

    def test_migration_from_existing_db(self):
        path=Path(self.tmp.name)/'legacy.sqlite3'
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE private_users(user_id INTEGER PRIMARY KEY, notifications_enabled INTEGER,started_at INTEGER,updated_at INTEGER)')
            conn.execute('INSERT INTO private_users VALUES(1,1,1,1)')
        migrated=Database(path)
        self.addCleanup(migrated.close)
        self.assertFalse(migrated.news_enabled(1))
        self.assertTrue(migrated.notifications_allowed(1))

class UpdaterTests(unittest.TestCase):
    def test_semver(self):
        self.assertLess(parse_version('1.0.0-rc.2'),parse_version('1.0.0'))
        self.assertLess(parse_version('1.0.0-rc.1'),parse_version('1.0.0-rc.2'))

    def test_reject_insecure_hosts(self):
        m={'schema':1,'channel':'beta','version':'1.0.0-rc.3','url':'https://evil.example/file.zip','sha256':'0'*64}
        with self.assertRaises(UpdateError):
            read_manifest(json.dumps(m).encode(),channel='beta',version='1.0.0-rc.2',hosts={'github.com'})

    def test_path_traversal_rejected(self):
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('../evil.py','x')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UpdateError):
                extract_verified_zip(archive.getvalue(),Path(directory)/'stage','2.0.0')

if __name__=='__main__':
    unittest.main()

class InstallationTests(unittest.TestCase):
    def test_install_and_rollback_code(self):
        from updater import install_prepared, restore_journal
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'base'; base.mkdir()
            (base/'VERSION').write_text('1.0.0-rc.2')
            (base/'main.py').write_text('old')
            stage=Path(d)/'stage';stage.mkdir()
            (stage/'VERSION').write_text('1.0.0-rc.3')
            (stage/'main.py').write_text('new')
            (stage/'release_notes.json').write_text('{}')
            journal=install_prepared(stage,['VERSION','main.py','release_notes.json'],base)
            self.assertEqual((base/'main.py').read_text(),'new')
            self.assertTrue((base/'release_notes.json').exists())
            restore_journal(journal,base)
            self.assertEqual((base/'main.py').read_text(),'old')
            self.assertFalse((base/'release_notes.json').exists())
            self.assertEqual((base/'VERSION').read_text(),'1.0.0-rc.2')
