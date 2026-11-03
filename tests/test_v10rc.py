"""Release candidate: appeals, reasons, opt-in DM and signed web authorization."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from krew.api import TelegramError
from krew.core import BotCore
from krew.db import Database
from krew.web import Application
from testsupport import signed_auth

CHAT=-100888777
TOKEN='BOT:abcdefghijklmnopqrstuvwxyz'

class API:
    def __init__(self):
        self.calls=[];self.admins={1};self.fail_dm=False;self.fail_get=False;self.fail_warn_notice=False
    def call(self,method,**kwargs):
        self.calls.append((method,kwargs))
        if method=='getChatMember':
            if self.fail_get:raise TelegramError('unavailable',503)
            return {'status':'administrator' if kwargs['user_id'] in self.admins else 'member'}
        if method=='sendMessage':
            if kwargs['chat_id']>0 and self.fail_dm:raise TelegramError('bot blocked by user',403)
            if kwargs['chat_id']<0 and self.fail_warn_notice: raise TelegramError('group notification failed',403)
            return {'message_id':100}
        if method in ('answerCallbackQuery','editMessageText','restrictChatMember'):
            return True
        raise AssertionError(f'unknown Telegram method {method}')

def pm(uid,text,reply_to=None):
    d={'chat':{'id':uid,'type':'private'},'from':{'id':uid,'first_name':'User'},'message_id':100,'text':text}
    if reply_to: d['reply_to_message']={'text':reply_to}
    return d

class RCTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'krew.db'
        self.db=Database(self.path)
        self.db.ensure_chat(CHAT,'Team <alpha>')
        self.api=API()
        self.core=BotCore(self.api,self.db,'krew_bot')
        self.web=Application(TOKEN,self.path,self.api)
        self.admin=signed_auth(TOKEN,1)
        self.user=signed_auth(TOKEN,7)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def report(self,uid=7,target=8,msg=50):
        self.assertEqual(self.db.report(CHAT,uid,target,msg),'created')
        return self.db.reports(CHAT)[0]['id']
    def web_decide(self,rid,action,body):
        return self.web.process('POST',f'/api/chats/{CHAT}/reports/{rid}/{action}',self.admin,body)
    def test_web_rejection_requires_real_reason(self):
        rid=self.report()
        for body in ({},{'reason':''},{'reason':'нет'},{'reason':' '},{'reason':'x'*301},{'reason':'ok','another':1}):
            code,_=self.web_decide(rid,'reject',body)
            self.assertEqual(code,400)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
    def test_web_rejection_persists_reason_and_history(self):
        rid=self.report()
        self.core.on_message(pm(7,'/start'))
        code,res=self.web_decide(rid,'reject',{'reason':'Нарушение не подтвердилось'})
        self.assertEqual(code,200)
        self.assertEqual(res['status'],'rejected')
        self.assertEqual(res['notification_status'],'sent')
        record=self.db.get_report(rid,CHAT)
        self.assertEqual(record['decision_reason'],'Нарушение не подтвердилось')
        self.assertGreater(record['resolved_at'],0)
        self.assertEqual(len(self.db.report_history(CHAT)),1)
        sent=[d for method,d in self.api.calls if method=='sendMessage' and d['chat_id']==7]
        self.assertTrue(any('Нарушение не подтвердилось' in d['text'] for d in sent))
        self.assertEqual(self.web_decide(rid,'reject',{'reason':'Повтор'})[0],409)
        self.assertEqual(len([d for method,d in self.api.calls if method=='sendMessage' and 'Решение по жалобе' in d['text']]),1)
    def test_reporter_cannot_view_another_report(self):
        rid=self.report()
        self.core.on_message(pm(10,'/start'))
        self.core.on_message(pm(10,'/myreports'))
        messages=[data['text'] for name,data in self.api.calls if name=='sendMessage' and data['chat_id']==10]
        self.assertTrue(any('пока нет обращений' in t for t in messages))
        self.assertFalse(any(f"Жалоба #{rid}" in t or f"#{rid} ·" in t for t in messages))
    def test_notifications_require_private_start(self):
        rid=self.report()
        _,res=self.web_decide(rid,'reject',{'reason':'Нарушения нет'})
        self.assertEqual(res['notification_status'],'not_started')
        self.assertFalse(any(name=='sendMessage' and data['chat_id']==7 for name,data in self.api.calls))
    def test_notifications_opt_out(self):
        self.core.on_message(pm(7,'/start'))
        self.core.on_message(pm(7,'/notify off'))
        self.api.calls.clear()
        rid=self.report()
        _,res=self.web_decide(rid,'reject',{'reason':'Слишком мало доказательств'})
        self.assertEqual(res['notification_status'],'disabled')
        self.assertFalse(any(name=='sendMessage' and data['chat_id']==7 for name,data in self.api.calls))
    def test_notifications_blocked_fail_without_data_loss(self):
        self.core.on_message(pm(7,'/start'))
        self.api.fail_dm=True
        rid=self.report()
        status,result=self.web_decide(rid,'reject',{'reason':'Нет нарушения правил'})
        self.assertEqual(status,200)
        self.assertEqual(result['notification_status'],'failed')
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'rejected')
        self.assertEqual(self.db.get_report(rid,CHAT)['notification_status'],'failed')
    def test_html_is_escaped_in_dm(self):
        self.core.on_message(pm(7,'/start'))
        self.api.calls.clear()
        rid=self.report()
        self.web_decide(rid,'reject',{'reason':'<b>Не подтвердилось</b>'})
        dm=[d for method,d in self.api.calls if method=='sendMessage' and d['chat_id']==7][0]
        self.assertIn('&lt;b&gt;Не подтвердилось&lt;/b&gt;',dm['text'])
        self.assertIn('Team &lt;alpha&gt;',dm['text'])
    def test_old_database_columns_migrate_in_place(self):
        self.db.conn.execute('DELETE FROM private_users')
        self.db.close()
        db=Database(self.path)
        self.assertIn('decision_reason',{x[1] for x in db.conn.execute('PRAGMA table_info(reports)')})
        db.close()
        # close second DB not twice
        self.db=Database(self.path)
    def test_signed_api_non_admin_denied(self):
        rid=self.report()
        code,_=self.web.process('POST',f'/api/chats/{CHAT}/reports/{rid}/reject',self.user,{'reason':'Нет нарушения'})
        self.assertEqual(code,403)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
    def test_web_race_only_one_wins(self):
        rid=self.report()
        self.core.on_message(pm(7,'/start'))
        for _ in range(2):self.web_decide(rid,'reject',{'reason':'Жалоба не подтверждена'})
        self.assertEqual(len(self.db.report_history(CHAT)),1)
    def test_warn_admin_denied_no_closed_report(self):
        self.api.admins={1,8}
        rid=self.report()
        code,_=self.web_decide(rid,'warn',{})
        self.assertEqual(code,403)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
    def test_api_unavailable_does_not_resolve_warning(self):
        rid=self.report()
        self.api.fail_get=True
        code,_=self.web_decide(rid,'warn',{})
        self.assertEqual(code,503)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
    def test_warn_deduplicated(self):
        rid=self.report()
        self.assertEqual(self.web_decide(rid,'warn',{})[0],200)
        self.assertEqual(self.db.get_warn(CHAT,8),1)
        self.assertEqual(self.web_decide(rid,'warn',{})[0],409)
        self.assertEqual(self.db.get_warn(CHAT,8),1)
    def test_private_reject_only_admin(self):
        rid=self.report()
        self.core.on_message(pm(7,f'/reject {CHAT} {rid} Причина от участника'))
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
        self.core.on_message(pm(1,f'/reject {CHAT} {rid} Причина модератора'))
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'rejected')
    def test_force_reply_for_reason(self):
        rid=self.report()
        cb={'id':'abc','from':{'id':1},'data':f'rep:{CHAT}:{rid}:reject',
            'message':{'chat':{'id':1,'type':'private'},'message_id':100}}
        self.core.on_callback(cb)
        pending=[d for name,d in self.api.calls if name=='sendMessage' and d['chat_id']==1][-1]
        self.assertTrue(pending['reply_markup']['force_reply'])
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
        self.core.on_message(pm(1,'Реклама отсутствует',reply_to=pending['text']))
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'rejected')
    def test_history_from_miniapp(self):
        rid=self.report()
        self.web_decide(rid,'reject',{'reason':'Нет доказательств'})
        code,data=self.web.process('GET',f'/api/chats/{CHAT}/reports',self.admin)
        self.assertEqual(code,200)
        self.assertEqual(data['reports'],[])
        self.assertEqual(data['history'][0]['id'],rid)
        self.assertEqual(data['history'][0]['decision_reason'],'Нет доказательств')
    def test_notifications_preserve_other_chats(self):
        self.db.ensure_chat(-100444,'Other')
        rid=self.report()
        self.assertEqual(self.web.process('POST',f'/api/chats/-100444/reports/{rid}/reject',self.admin,{'reason':'Other group'})[0],409)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')
    def test_invalid_reason_control_chars_and_bloat(self):
        rid=self.report()
        bad={'reason':'A'*2000}
        self.assertEqual(self.web_decide(rid,'reject',bad)[0],400)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'open')

if __name__=='__main__':unittest.main()

class LegacyDatabaseMigrationTest(unittest.TestCase):
    def test_additive_upgrade_preserves_old_reports(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.db'
            with sqlite3.connect(path) as conn:
                conn.execute('''CREATE TABLE reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,
                    reporter_id INTEGER NOT NULL,target_id INTEGER NOT NULL,
                    target_message_id INTEGER NOT NULL,created INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',resolved_by INTEGER,
                    UNIQUE(chat_id,reporter_id,target_message_id))''')
                import time
                conn.execute('INSERT INTO reports(chat_id,reporter_id,target_id,target_message_id,created) VALUES(?,?,?,?,?)',
                             (-100,77,88,1,int(time.time())))
            db=Database(path)
            try:
                record=db.get_report(1,-100)
                self.assertEqual(record['status'],'open')
                self.assertEqual(record['reporter_id'],77)
                self.assertIn('notification_status',record)
                self.assertEqual(record['notification_status'],'pending')
                self.assertTrue(db.decide_report(1,-100,1,'rejected','Не соответствует критериям'))
            finally:db.close()

class TargetNoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'x.db'
        self.db=Database(self.path);self.db.ensure_chat(CHAT,'Team')
        self.api=API();self.core=BotCore(self.api,self.db,'krew_bot')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_private_warning_reaches_target_no_reporter_leak(self):
        self.core.on_message(pm(7,'/start'))
        self.core.on_message(pm(8,'/start'))
        self.db.report(CHAT,7,8,52)
        rid=self.db.reports(CHAT)[0]['id']
        self.api.calls.clear()
        result=self.core.decide_report(CHAT,rid,1,'warn','')
        self.assertEqual(result['target_notification_status'],'sent')
        notice=[data['text'] for name,data in self.api.calls if name=='sendMessage' and data['chat_id']==8]
        self.assertEqual(len(notice),1)
        self.assertIn('Предупреждение',notice[0])
        self.assertNotIn('7',notice[0])
        self.assertEqual(self.db.get_report(rid,CHAT)['target_notification_status'],'sent')
    def test_target_not_started_keeps_decision(self):
        self.db.report(CHAT,7,8,52);rid=self.db.reports(CHAT)[0]['id']
        result=self.core.decide_report(CHAT,rid,1,'warn','')
        self.assertEqual(result['target_notification_status'],'not_started')
        self.assertEqual(self.db.get_warn(CHAT,8),1)
        self.assertEqual(self.db.get_report(rid,CHAT)['status'],'warned')
