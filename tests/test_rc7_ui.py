"""Regression coverage for compact help and Telegram Rich Messages."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from krew.api import TelegramError
from krew.core import BotCore
from krew.db import Database
from krew.ui import SECTIONS, help_page, keyboard, report


class FakeAPI:
    def __init__(self, rich_failure=None, edit_failure=None):
        self.calls=[]
        self.rich_failure=rich_failure
        self.edit_failure=edit_failure

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if method=='getChatMember':
            return {'status':'administrator' if kwargs['user_id']==1 else 'member'}
        if method=='sendRichMessage' and self.rich_failure:
            raise self.rich_failure
        if method=='editMessageText' and 'rich_message' in kwargs and self.edit_failure:
            raise self.edit_failure
        if method in ('sendMessage','sendRichMessage','editMessageText'):
            return {'message_id':101}
        return True


class UITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'test.sqlite3')
        self.addCleanup(self.db.close)
        self.api=FakeAPI()
        self.bot=BotCore(self.api,self.db,'krew_test')

    def send(self, command, user=5, private=False):
        chat={'id':5 if private else -100,'type':'private' if private else 'supergroup','title':'Test'}
        self.bot.on_message({'message_id':10,'chat':chat,'from':{'id':user,'first_name':'Test'},'text':command})

    def click(self,page,private=False):
        chat={'id':5 if private else -100,'type':'private' if private else 'supergroup'}
        self.bot.on_callback({'id':'callback-123','from':{'id':5},'data':'help:'+page,
                              'message':{'message_id':101,'chat':chat}})

    def test_help_home_has_six_small_sections(self):
        self.send('/help')
        method,data=self.api.calls[-1]
        self.assertEqual(method,'sendMessage')
        self.assertLess(len(data['text']),500)
        rows=data['reply_markup']['inline_keyboard']
        self.assertEqual([len(r) for r in rows],[2,2,2])
        self.assertEqual(rows[0][0]['callback_data'],'help:start')

    def test_private_start_and_help_open_same_menu(self):
        self.send('/start',private=True)
        self.send('/help',private=True)
        method,data=self.api.calls[-1]
        self.assertEqual(method,'sendMessage')
        self.assertIn('help:games',str(data['reply_markup']))

    def test_mini_app_button_only_private_and_https(self):
        with patch.dict('os.environ',{'WEBAPP_URL':'https://panel.example'}):
            self.send('/help',private=True)
            self.assertIn('web_app',str(self.api.calls[-1][1]['reply_markup']))
            self.send('/help')
            self.assertNotIn('web_app',str(self.api.calls[-1][1]['reply_markup']))
        with patch.dict('os.environ',{'WEBAPP_URL':'http://localhost'}):
            self.send('/help',private=True)
            self.assertNotIn('web_app',str(self.api.calls[-1][1]['reply_markup']))

    def test_help_navigation_edits_one_message_with_table(self):
        self.send('/help')
        self.click('games')
        updates=[d for method,d in self.api.calls if method=='editMessageText']
        self.assertEqual(len(updates),1)
        self.assertEqual(updates[0]['message_id'],101)
        self.assertIn('<table striped compact>',updates[0]['rich_message']['html'])
        self.assertIn('/quiz',updates[0]['rich_message']['html'])
        self.click('home')
        self.assertEqual(len([x for x in self.api.calls if x[0]=='sendMessage']),1)
        self.assertEqual(len([x for x in self.api.calls if x[0]=='editMessageText']),2)

    def test_unknown_help_callback_does_not_run_commands(self):
        self.click('delete_everything')
        self.assertFalse(any(m.startswith('editMessage') for m,_ in self.api.calls))
        self.assertEqual(self.api.calls[-1][0],'answerCallbackQuery')

    def test_rich_help_edit_falls_back_to_html_on_unsupported_api(self):
        self.api.edit_failure=TelegramError('Bad request: unsupported',400)
        self.click('moderation')
        edits=[d for method,d in self.api.calls if method=='editMessageText']
        self.assertEqual(len(edits),2)
        self.assertIn('rich_message',edits[0])
        self.assertIn('/mute',edits[1]['text'])
        self.assertIn('reply_markup',edits[1])

    def test_group_stats_is_rich_and_admin_only(self):
        self.send('/stats',user=5)
        self.assertEqual(self.api.calls[-1][0],'sendMessage')
        self.assertIn('только администраторам',self.api.calls[-1][1]['text'])
        self.send('/stats',user=1)
        method,body=self.api.calls[-1]
        self.assertEqual(method,'sendRichMessage')
        self.assertIn('<table',body['rich_message']['html'])
        self.assertIn('Сообщений',body['rich_message']['html'])

    def test_profile_table_and_user_supplied_name_escaped(self):
        self.bot.on_message({'message_id':10,'chat':{'id':-100,'type':'supergroup','title':'Test'},
                             'from':{'id':5,'first_name':'<admin>'},'text':'/profile'})
        method,body=self.api.calls[-1]
        self.assertEqual(method,'sendRichMessage')
        self.assertIn('&lt;admin&gt;',body['rich_message']['html'])
        self.assertNotIn('<admin>',body['rich_message']['html'])

    def test_rich_unsupported_falls_back_once(self):
        self.api.rich_failure=TelegramError('Bad request',400)
        self.send('/stats',user=1)
        methods=[method for method,_ in self.api.calls if method in ('sendRichMessage','sendMessage')]
        self.assertEqual(methods,['sendRichMessage','sendMessage'])
        self.assertIn('Сообщений',self.api.calls[-1][1]['text'])

    def test_rich_network_failure_never_double_sends(self):
        self.api.rich_failure=TelegramError('Connection lost',0)
        with self.assertRaises(TelegramError):
            self.bot.send_rich(-100,'<h3>Hello</h3>','Hello')
        methods=[m for m,_ in self.api.calls if m in ('sendRichMessage','sendMessage')]
        self.assertEqual(methods,['sendRichMessage'])

    def test_all_pages_and_keyboard_payloads_are_valid(self):
        for page in SECTIONS:
            plain,rich=help_page(page)
            self.assertTrue(plain and rich)
            self.assertLess(len(plain),4096)
            for row in keyboard(page)['inline_keyboard']:
                for button in row:
                    if 'callback_data' in button:
                        self.assertLessEqual(len(button['callback_data'].encode()),64)

    def test_report_escapes_dynamic_values_for_both_formats(self):
        plain,rich=report('Stats', [('Test','<unsafe> & value')])
        self.assertIn('&lt;unsafe&gt; &amp; value',plain)
        self.assertIn('&lt;unsafe&gt; &amp; value',rich)
        self.assertNotIn('<unsafe>',rich)

if __name__=='__main__':
    unittest.main()
