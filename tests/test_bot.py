import tempfile
import unittest
from pathlib import Path
from krew.core import BotCore
from krew.db import Database

class FakeAPI:
    def __init__(self):
        self.requests = []
    def call(self, method, **kwargs):
        self.requests.append((method, kwargs))
        if method == 'getChatMember':
            return {'status': 'administrator' if kwargs['user_id'] == 1 else 'member'}
        if method == 'sendMessage':
            return {'message_id': 101}
        return True


def message(user_id, text, reply_to=None, chat_id=-100):
    msg = {'message_id': 3, 'chat': {'id': chat_id, 'type':'supergroup', 'title':'Тест'},
           'from':{'id':user_id, 'first_name':'Пользователь'}, 'text':text}
    if reply_to:
        msg['reply_to_message'] = {'from':{'id':reply_to, 'first_name':'Друг'}}
    return msg

class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'db.sqlite3')
        self.api = FakeAPI()
        self.core = BotCore(self.api, self.db, 'test_chat_bot')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_regular_user_cannot_mute(self):
        self.core.on_message(message(5, '/mute 10m', reply_to=6))
        self.assertFalse(any(m == 'restrictChatMember' for m, _ in self.api.requests))
        self.assertIn('только администраторам', self.api.requests[-1][1]['text'])

    def test_admin_mutes_regular_user(self):
        self.core.on_message(message(1, '/mute 10m Оскорбления', reply_to=6))
        calls = [p for m, p in self.api.requests if m == 'restrictChatMember']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['user_id'], 6)
        self.assertFalse(calls[0]['permissions']['can_send_messages'])

    def test_admin_target_protected(self):
        self.core.on_message(message(1, '/ban', reply_to=1))
        self.assertFalse(any(m == 'banChatMember' for m, _ in self.api.requests))

    def test_antilinks_with_admin_toggle(self):
        self.db.toggle(-100, 'antilinks')
        self.core.on_message(message(5, 'Зайди на t.me/foobar'))
        self.assertTrue(any(m == 'deleteMessage' for m, _ in self.api.requests))
        self.assertEqual(self.db.get_warn(-100, 5), 1)

    def test_auto_mute_after_third_deleted_link(self):
        self.db.toggle(-100, 'antilinks')
        for _ in range(3):
            self.core.on_message(message(5, 'здесь ссылка https://example.org'))
        self.assertTrue(any(m == 'restrictChatMember' for m, _ in self.api.requests))
        self.assertEqual(self.db.get_warn(-100, 5), 0)

    def test_callback_admin_only(self):
        cb = lambda user: {'id':'cbid', 'from':{'id':user}, 'data':'cfg:antilinks',
                           'message':{'message_id':101, 'chat':{'id':-100, 'type':'supergroup'}}}
        self.core.on_callback(cb(5))
        self.assertFalse(self.db.get_chat(-100)['antilinks'])
        self.core.on_callback(cb(1))
        self.assertTrue(self.db.get_chat(-100)['antilinks'])

    def test_quiz_awards_only_once(self):
        self.core.on_message(message(5, '/quiz'))
        game = next(p for m, p in self.api.requests if m == 'sendMessage' and 'Викторина' in p['text'])
        data = game['reply_markup']['inline_keyboard'][0][0]['callback_data']
        quiz_id = int(data.split(':')[1])
        correct = self.db.conn.execute('SELECT correct FROM quizzes WHERE quiz_id=?', (quiz_id,)).fetchone()[0]
        cb = {'id':'cbid', 'from':{'id':5}, 'data':f'q:{quiz_id}:{correct}',
              'message':{'message_id':101, 'chat':{'id':-100, 'type':'supergroup'}}}
        self.core.on_callback(cb)
        self.core.on_callback(cb)
        self.assertEqual(self.db.profile(-100, 5)['coins'], 15)

if __name__ == '__main__':
    unittest.main()
