"""Community+ missions and gratitude must be server-authoritative."""
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from krew.core import BotCore
from krew.db import Database
from krew.web import Application
from testsupport import DummyAPI, msg, signed_auth

class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'db.sqlite3'
        self.db=Database(self.path)
        self.db.ensure_chat(-100,'Test')
        self.api=DummyAPI()
        self.bot=BotCore(self.api,self.db,'testbot')
        self.app=Application('test-token',self.path,self.api)
    def tearDown(self):self.db.close();self.tmp.cleanup()

    def test_activity_credits_one_daily_step_only_when_xp_given(self):
        start=int(time.time())-150
        day=datetime.fromtimestamp(start,timezone.utc).date().isoformat()
        self.assertTrue(self.db.activity(-100,2,'Alex',now=start))
        self.assertFalse(self.db.activity(-100,2,'Alex',now=start+5))
        self.assertTrue(self.db.activity(-100,2,'Alex',now=start+61))
        self.assertEqual(self.db.mission(-100,2,day)['messages'],2)

    def test_claim_only_after_goal_once(self):
        day='2026-11-03'
        self.assertEqual(self.db.claim_mission(-100,2,day),'not_ready')
        self.db.ensure_member(-100,2,'Test')
        self.db.conn.execute('INSERT INTO member_day(chat_id,user_id,day,messages) VALUES(?,?,?,?)',(-100,2,day,5))
        self.assertEqual(self.db.claim_mission(-100,2,day),'claimed')
        self.assertEqual(self.db.claim_mission(-100,2,day),'already')
        self.assertEqual(self.db.profile(-100,2)['coins'],35)
        self.assertEqual(self.db.profile(-200,2)['coins'],0)

    def test_mission_not_ready_four_messages(self):
        day='2026-11-03'
        self.db.conn.execute('INSERT INTO member_day(chat_id,user_id,day,messages) VALUES(?,?,?,?)',(-100,2,day,4))
        self.assertEqual(self.db.claim_mission(-100,2,day),'not_ready')
        self.assertEqual(self.db.profile(-100,2)['coins'],0)

    def test_thanks_is_once_per_giver_day_and_chat(self):
        day='2026-11-03'
        self.assertTrue(self.db.give_thanks(-100,2,3,day))
        self.assertFalse(self.db.give_thanks(-100,2,4,day))
        self.assertTrue(self.db.give_thanks(-100,5,3,day))
        self.assertTrue(self.db.give_thanks(-200,2,4,day))
        self.assertTrue(self.db.give_thanks(-100,2,3,'2026-11-04'))
        self.assertEqual(self.db.profile(-100,3)['reputation'],3)
        self.assertEqual(self.db.profile(-100,4)['reputation'],0)
        self.assertEqual(self.db.profile(-200,4)['reputation'],1)

    def test_thanks_self_abuse_rejected(self):
        self.assertFalse(self.db.give_thanks(-100,2,2))
        self.assertFalse(self.db.give_thanks(-100,0,2))

    def test_bot_thanks_requires_reply_and_fun(self):
        self.bot.on_message(msg(2,'/thanks'))
        self.assertEqual(self.db.profile(-100,3)['reputation'],0)
        self.bot.on_message(msg(2,'/thanks',reply_to=3))
        self.assertEqual(self.db.profile(-100,3)['reputation'],1)
        self.bot.on_message(msg(2,'/thanks',reply_to=3))
        self.assertEqual(self.db.profile(-100,3)['reputation'],1)

    def test_fun_off_cannot_claim_or_thank(self):
        self.db.set_setting(-100,'fun',False)
        self.bot.on_message(msg(2,'/thanks',reply_to=3))
        self.assertEqual(self.db.profile(-100,3)['reputation'],0)
        self.bot.on_message(msg(2,'/claim'))
        self.assertEqual(self.db.profile(-100,2)['coins'],0)

    def test_min_app_community_admin_only(self):
        good=self.app.process('GET','/api/chats/-100/community',signed_auth('test-token',1))
        self.assertEqual(good[0],200)
        self.assertEqual(good[1]['community']['mission_goal'],5)
        self.assertEqual(self.app.process('GET','/api/chats/-100/community',signed_auth('test-token',2))[0],403)

    def test_community_reports_reputation(self):
        self.db.give_thanks(-100,2,3)
        self.db.give_thanks(-100,4,3)
        report=self.db.community(-100)
        self.assertEqual(report['thanks_today'],2)
        self.assertEqual(report['top_reputation'][0]['user_id'],3)
        self.assertEqual(report['top_reputation'][0]['reputation'],2)

    def test_04_to_06_migrations_preserve_progress(self):
        self.db.ensure_member(-100,7,'Member')
        self.db.add_coins(-100,7,200)
        self.db.warn(-100,7)
        self.db.close()
        upgraded=Database(self.path)
        self.assertEqual(upgraded.profile(-100,7)['coins'],200)
        self.assertEqual(upgraded.get_warn(-100,7),1)
        self.assertEqual(upgraded.profile(-100,7)['reputation'],0)
        upgraded.close()
        self.db=Database(self.path)

if __name__=='__main__':unittest.main()
