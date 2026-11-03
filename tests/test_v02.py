"""KREW 0.2.0 regression tests — permissions, raid, captcha, reports, games and migration."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from krew.core import BotCore
from krew.db import Database
from krew.rules import disallowed_link, normalize_domain


class StubAPI:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def call(self, method, **kwargs):
        from krew.api import TelegramError
        self.calls.append((method, kwargs))
        if method in self.fail:
            raise TelegramError('Mock Telegram error', 403)
        if method == 'getChatMember':
            if kwargs['user_id'] == 111111:
                return {'status':'administrator', 'can_delete_messages':True, 'can_restrict_members':True}
            return {'status': 'administrator' if kwargs['user_id'] == 1 else 'member'}
        if method == 'getMe':
            return {'id':111111, 'username':'krewtestbot'}
        if method == 'getChat':
            return {'permissions': {'can_send_messages': True, 'can_send_polls': False}}
        if method == 'sendMessage':
            return {'message_id': 999 + len(self.calls)}
        return True

    def of(self, method):
        return [v for m,v in self.calls if m == method]


def message(user_id, content='', chat_id=-100, reply=None):
    msg = {'message_id': 5, 'chat': {'id': chat_id, 'type': 'supergroup', 'title': 'Тест'},
           'from': {'id':user_id, 'first_name':'Новый <пользователь>'}, 'text': content}
    if reply:
        msg['reply_to_message'] = {'message_id': 20, 'from': {'id':reply, 'first_name':'Друг'}}
    return msg


def cb(user_id, data, message_id, chat_id=-100):
    return {'id': 'cb1', 'from': {'id':user_id}, 'data':data,
            'message': {'message_id':message_id, 'chat':{'id':chat_id,'type':'supergroup'}}}


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name)/'krew.sqlite3')
        self.api = StubAPI()
        self.bot = BotCore(self.api, self.db, 'krewtestbot')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_new_settings_opt_in(self):
        state = self.db.get_chat(-100)
        for field in ('captcha', 'antiforward', 'antiraid'):
            self.assertEqual(state[field], 0)
            self.db.toggle(-100, field)
            self.assertEqual(self.db.get_chat(-100)[field], 1)
        self.assertEqual(self.db.get_chat(-200)['captcha'], 0)

    def test_diagnostics_admin_only(self):
        self.bot.on_message(message(5, '/diagnostics'))
        self.assertFalse(self.api.of('getMe'))
        self.bot.on_message(message(1, '/diagnostics'))
        self.assertEqual(len(self.api.of('getMe')), 1)
        self.assertIn('✅ Удаление', self.api.of('sendMessage')[-1]['text'])

    def test_whitelist_parser_blocks_deceptive_suffix(self):
        self.assertEqual(normalize_domain('WWW.YouTube.com'), 'youtube.com')
        for domain in ('https://youtube.com', 'evil.com/path', 'localhost', 'a..com'):
            with self.assertRaises(ValueError):
                normalize_domain(domain)
        self.assertFalse(disallowed_link('https://m.youtube.com/a', [], ['youtube.com']))
        self.assertTrue(disallowed_link('youtube.com.evil.net', [], ['youtube.com']))
        self.assertTrue(disallowed_link('без ссылки', [{'type':'text_link', 'url':'https://evil.net'}], ['youtube.com']))
        self.assertFalse(disallowed_link('без ссылки', [{'type':'text_link', 'url':'https://youtube.com/a'}], ['youtube.com']))

    def test_allowlist_really_prevents_delete(self):
        self.db.toggle(-100, 'antilinks')
        self.db.add_domain(-100, 'youtube.com')
        self.bot.on_message(message(6, 'https://m.youtube.com/watch'))
        self.assertFalse(self.api.of('deleteMessage'))
        self.bot.on_message(message(6, 'https://youtube.com.evil.org'))
        self.assertEqual(len(self.api.of('deleteMessage')), 1)

    def test_forward_filter_edited_message(self):
        self.db.toggle(-100, 'antiforward')
        forwarded = message(5, 'обычный текст')
        forwarded['forward_origin'] = {'type':'user', 'sender_user':{'id':7}}
        self.bot.on_message(forwarded)
        self.assertEqual(self.db.get_warn(-100, 5), 1)
        self.db.toggle(-100, 'antilinks')
        self.bot.on_edited_message(message(5, 'https://spam.com'))
        self.assertEqual(self.db.get_warn(-100, 5), 2)
        self.assertEqual(self.db.profile(-100, 5)['messages'], 0)

    def test_raid_requires_opt_in(self):
        for _ in range(5):
            self.bot.on_message(self.join(8))
        self.assertEqual(self.db.get_chat(-100)['raid_until'], 0)
        self.db.toggle(-100, 'antiraid')
        for i in range(5):
            self.bot.on_message(self.join(100+i, chat_id=-200))
        # other chat didn't opt in
        self.assertEqual(self.db.get_chat(-200)['raid_until'], 0)
        for i in range(5):
            self.bot.on_message(self.join(200+i))
        self.assertGreater(self.db.get_chat(-100)['raid_until'], int(time.time()))

    def join(self, joined_id, chat_id=-100):
        msg = message(1, '', chat_id=chat_id)
        msg['new_chat_members'] = [{'id':joined_id, 'first_name':'Новый', 'is_bot':False}]
        return msg

    def test_captcha_correct_and_other_user_cannot_solve(self):
        self.db.toggle(-100, 'captcha')
        self.bot.on_message(self.join(55))
        challenge = self.db.challenge(-100, 55)
        self.assertIsNotNone(challenge)
        self.assertEqual(len(self.api.of('restrictChatMember')), 1)
        wrong_user_cb = cb(56, f'v:55:{challenge["correct"]}', challenge['message_id'])
        self.bot.on_callback(wrong_user_cb)
        self.assertIsNotNone(self.db.challenge(-100,55))
        self.bot.on_callback(cb(55, f'v:55:{challenge["correct"]}', challenge['message_id']))
        self.assertIsNone(self.db.challenge(-100,55))
        restores = self.api.of('restrictChatMember')
        self.assertEqual(len(restores), 2)
        self.assertFalse(restores[1]['permissions']['can_send_polls'])
        self.assertTrue(restores[1]['permissions']['can_send_messages'])

    def test_captcha_wrong_answer_not_unrestricted(self):
        self.db.toggle(-100, 'captcha')
        self.bot.on_message(self.join(66))
        c = self.db.challenge(-100, 66)
        self.bot.on_callback(cb(66, f'v:66:{(c["correct"]+1)%3}', c['message_id']))
        self.assertEqual(self.db.challenge(-100,66)['attempts'], 1)
        self.assertEqual(len(self.api.of('restrictChatMember')), 1)

    def test_captcha_expiry_kicks_and_releases(self):
        self.db.new_challenge(-100, 70, '1+1', 0, '2,3,4', int(time.time()) - 3)
        self.db.set_challenge_message(-100, 70, 100)
        self.bot.maintenance()
        self.assertEqual(len(self.api.of('banChatMember')), 1)
        self.assertEqual(len(self.api.of('unbanChatMember')), 1)
        self.assertIsNone(self.db.challenge(-100,70))
        self.assertEqual(self.db.recent_actions(-100)[0]['action'], 'captcha_timeout')

    def test_captcha_expiry_retry_on_api_failure(self):
        self.db.new_challenge(-100, 71, '1+1', 0, '2,3,4', int(time.time()) - 1)
        self.api.fail.add('banChatMember')
        self.bot.maintenance()
        self.assertIsNotNone(self.db.challenge(-100,71))
        self.api.fail.clear()
        self.bot.maintenance()
        self.assertIsNone(self.db.challenge(-100,71))

    def test_staff_can_turn_on_raid_manually(self):
        self.bot.on_message(message(6,'/raid 10m'))
        self.assertEqual(self.db.get_chat(-100)['raid_until'], 0)
        self.bot.on_message(message(1,'/raid 10m'))
        self.assertGreater(self.db.get_chat(-100)['raid_until'], int(time.time()))
        self.bot.on_message(self.join(88))
        self.assertIsNotNone(self.db.challenge(-100,88))
        self.bot.on_message(message(1,'/raid off'))
        self.assertEqual(self.db.get_chat(-100)['raid_until'], 0)

    def test_report_queue_permissions_and_dedup(self):
        self.bot.on_message(message(5,'/report', reply=6))
        self.assertEqual(len(self.db.reports(-100)), 1)
        self.assertEqual(self.db.reports(-100)[0]['target_id'], 6)
        self.assertEqual(self.db.report(-100,5,6,20), 'duplicate')
        self.bot.on_message(message(5,'/reports'))
        self.assertIn('только администраторам', self.api.of('sendMessage')[-1]['text'])
        self.bot.on_message(message(1,'/reports'))
        group_message = self.api.of('sendMessage')[-1]
        self.assertNotIn('От ID', group_message['text'])
        self.assertIn('reports_-100', group_message['reply_markup']['inline_keyboard'][0][0]['url'])
        self.bot.on_message({'message_id':6, 'chat':{'id':1,'type':'private'},
                             'from':{'id':1,'first_name':'Админ'}, 'text':'/reports -100'})
        self.assertIn('Жалоба', self.api.of('sendMessage')[-1]['text'])
        report_id = self.db.reports(-100)[0]['id']
        self.bot.on_callback({'id':'cb', 'from':{'id':5}, 'data':f'rep:-100:{report_id}:close',
                              'message':{'message_id':101,'chat':{'id':5, 'type':'private'}}})
        self.assertEqual(self.db.reports(-100)[0]['status'], 'open')
        self.bot.on_callback({'id':'cb', 'from':{'id':1}, 'data':f'rep:-100:{report_id}:close',
                              'message':{'message_id':101,'chat':{'id':1, 'type':'private'}}})
        self.assertEqual(self.db.reports(-100), [])

    def test_report_warn_only_once_and_cross_chat_protected(self):
        self.bot.on_message(message(5,'/report', reply=6))
        report_id = self.db.reports(-100)[0]['id']
        self.bot.on_callback({'id':'c', 'from':{'id':1}, 'data':f'rep:-200:{report_id}:warn',
                              'message':{'message_id':102,'chat':{'id':1,'type':'private'}}})
        self.assertEqual(self.db.get_warn(-100,6), 0)
        private_cb = {'id':'c', 'from':{'id':1}, 'data':f'rep:-100:{report_id}:warn',
                      'message':{'message_id':102,'chat':{'id':1,'type':'private'}}}
        self.bot.on_callback(private_cb)
        self.assertEqual(self.db.get_warn(-100,6), 1)
        self.bot.on_callback(private_cb)
        self.assertEqual(self.db.get_warn(-100,6), 1)

    def test_reports_per_hour_limit(self):
        for i in range(3):
            self.assertEqual(self.db.report(-100, 55, 77, 100+i, now=5000), 'created')
        self.assertEqual(self.db.report(-100, 55, 77, 200, now=5000), 'limited')
        self.assertEqual(self.db.report(-100, 55, 77, 200, now=9000), 'created')

    def test_rps_authorized_once_and_correct_logic(self):
        # rock=0 beats scissors=1, scissors=1 beats paper=2, paper=2 beats rock=0.
        for bot_choice, user_choice in [(1,0),(2,1),(0,2)]:
            game = self.db.create_rps(-100,55,bot_choice,int(time.time())+100)
            self.assertEqual(self.db.play_rps(game,-100,56,user_choice), 'not_yours')
            self.assertEqual(self.db.play_rps(game,-200,55,user_choice), 'not_yours')
            self.assertEqual(self.db.play_rps(game,-100,55,user_choice), 'win')
            self.assertEqual(self.db.play_rps(game,-100,55,user_choice), 'already')
        self.assertEqual(self.db.profile(-100,55)['coins'], 24)

    def test_daily_streak_reset_and_continuation(self):
        self.db.daily(-100,10,'Иван',10,'2026-11-01')
        self.db.daily(-100,10,'Иван',10,'2026-11-02')
        self.assertEqual(self.db.profile(-100,10)['daily_streak'], 2)
        self.db.daily(-100,10,'Иван',10,'2026-11-04')
        self.assertEqual(self.db.profile(-100,10)['daily_streak'], 1)

    def test_unsafe_welcome_escaped(self):
        self.db.set_welcome_text(-100, '<img src=x> Привет {user}')
        self.bot.on_message(self.join(66))
        body = self.api.of('sendMessage')[-1]['text']
        self.assertIn('&lt;img', body)
        self.assertIn('tg://user?id=66', body)


class MigrationTests(unittest.TestCase):
    def test_open_old_db_without_losing_data(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name)/'old.sqlite3'
        conn = sqlite3.connect(path)
        conn.executescript('''
        CREATE TABLE chats(chat_id INTEGER PRIMARY KEY, title TEXT, antispam INTEGER DEFAULT 1,
          antilinks INTEGER DEFAULT 0, welcome INTEGER DEFAULT 1, fun INTEGER DEFAULT 1,
          levels INTEGER DEFAULT 1, rules TEXT DEFAULT '', warn_limit INTEGER DEFAULT 3,
          created_at INTEGER DEFAULT 0);
        CREATE TABLE members(chat_id INTEGER, user_id INTEGER, name TEXT DEFAULT '', xp INTEGER DEFAULT 0,
          coins INTEGER DEFAULT 0, messages INTEGER DEFAULT 0, last_xp INTEGER DEFAULT 0,
          last_daily TEXT DEFAULT '', active_badge TEXT DEFAULT '', PRIMARY KEY(chat_id,user_id));
        INSERT INTO chats(chat_id,title,antispam,antilinks,welcome,fun,levels,rules,warn_limit)
          VALUES(-100,'Чат',1,1,1,1,1,'Старые правила',3);
        INSERT INTO members(chat_id,user_id,name,xp,coins,messages,last_xp,last_daily,active_badge)
          VALUES(-100,42,'Паша',400,321,40,0,'2026-11-02','star');
        ''')
        conn.close()
        migrated = Database(path)
        self.assertEqual(migrated.get_chat(-100)['rules'], 'Старые правила')
        self.assertEqual(migrated.profile(-100,42)['coins'], 321)
        self.assertEqual(migrated.profile(-100,42)['xp'], 400)
        self.assertEqual(migrated.get_chat(-100)['captcha'], 0)
        migrated.close()
        tmp.cleanup()


if __name__ == '__main__':
    unittest.main()

class MigrationScriptTests(unittest.TestCase):
    def test_script_can_import(self):
        from upgrade import upgrade
        self.assertTrue(callable(upgrade))

    def test_script_copies_database_and_env_without_overwriting(self):
        from unittest.mock import patch
        from upgrade import upgrade
        tmp = tempfile.TemporaryDirectory()
        old, new = Path(tmp.name)/'previous', Path(tmp.name)/'new'
        (old/'data').mkdir(parents=True)
        new.mkdir()
        (old/'.env').write_text('BOT_TOKEN=TEST_NOT_REAL_TOKEN\n', encoding='utf8')
        with sqlite3.connect(old/'data'/'krew.sqlite3') as db:
            db.execute('CREATE TABLE information(value INTEGER)')
            db.execute('INSERT INTO information VALUES (12345)')
        with patch('upgrade.NEW', new):
            messages = upgrade(old)
            self.assertTrue(any('SQLite' in m for m in messages))
            self.assertIn('TEST_NOT_REAL_TOKEN', (new/'.env').read_text())
            with sqlite3.connect(new/'data'/'krew.sqlite3') as db:
                self.assertEqual(db.execute('SELECT value FROM information').fetchone()[0], 12345)
            # Destination data takes precedence even if original changes.
            with sqlite3.connect(old/'data'/'krew.sqlite3') as db:
                db.execute('UPDATE information SET value=999')
            upgrade(old)
            with sqlite3.connect(new/'data'/'krew.sqlite3') as db:
                self.assertEqual(db.execute('SELECT value FROM information').fetchone()[0], 12345)
        tmp.cleanup()
