"""KREW 0.4 API + compatibility + permission tests."""
import hmac,hashlib,json,tempfile,time,unittest
from pathlib import Path
from urllib.parse import urlencode
from krew.web import Application
from krew.db import Database
from krew.api import TelegramError

TOKEN='BOT:abcdefghijklmnopqrstuvwxyz'
def auth(uid=51):
  p={'auth_date':str(int(time.time())), 'user':json.dumps({'id':uid,'first_name':'Admin'},separators=(',',':'))}
  s='\n'.join(f'{k}={v}' for k,v in sorted(p.items()))
  k=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
  p['hash']=hmac.new(k,s.encode(),hashlib.sha256).hexdigest()
  return 'tma '+urlencode(p)
class MockTelegram:
  def __init__(self):self.admins={51};self.calls=[];self.fail_send=False
  def call(self,method,**kwargs):
    self.calls.append((method,kwargs))
    if method=='getChatMember':return {'status':'administrator' if kwargs['user_id'] in self.admins else 'member'}
    if method=='sendMessage':
      if self.fail_send: raise TelegramError('simulated timeout')
      return {'message_id':1}
    if method=='restrictChatMember':return True
    raise AssertionError(method)
class V04Test(unittest.TestCase):
  def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'x.sqlite3'
    self.db=Database(self.path);self.db.ensure_chat(-100,'Тестовый');self.api=MockTelegram()
    self.app=Application(TOKEN,self.path,self.api)
    self.login=auth()
  def tearDown(self):self.db.close();self.tmp.cleanup()
  def route(self,endpoint,method='GET',body=None,who=None):
    return self.app.process(method,'/api/chats/-100/'+endpoint,who or self.login,body)
  def test_analytics_range(self):
    self.db.track(-100,'messages',6)
    self.db.track(-100,'joins',2)
    code,data=self.route('analytics');self.assertEqual(code,200)
    self.assertEqual(len(data['timeline']),14)
    self.assertEqual(data['timeline'][-1]['messages'],6)
    self.assertEqual(data['timeline'][-1]['joins'],2)
  def test_add_remove_domains_and_words(self):
    for ep,value in [('words','спам'),('domains','youtube.com')]:
      self.assertEqual(self.route(ep,'POST',{'action':'add','value':value})[0],200)
      self.assertIn(value,self.route('rulesets')[1][ep])
      self.assertEqual(self.route(ep,'POST',{'action':'add','value':value})[0],409)
      self.assertEqual(self.route(ep,'POST',{'action':'remove','value':value})[0],200)
      self.assertNotIn(value,self.route('rulesets')[1][ep])
    self.assertGreaterEqual(len(self.route('audit')[1]['audit']),4)
  def test_domain_rules_validation(self):
    for d in ['evil.com/subpath','localhost','https://foo.com', 'foo.com:8080']:
      self.assertEqual(self.route('domains','POST',{'action':'add','value':d})[0],400)
  def test_unknown_action_denied(self):
    self.assertEqual(self.route('words','POST',{'action':'drop_database','value':'test'})[0],400)
  def test_non_admin_denied_for_all_routes(self):
    no=auth(88)
    for ep,method,payload in [('analytics','GET',None),('audit','GET',None),('rulesets','GET',None),
                              ('words','POST',{'action':'add','value':'hello'})]:
      self.assertEqual(self.route(ep,method,payload,no)[0],403)
  def test_warn_report_once(self):
    self.assertEqual(self.db.report(-100,99,72,5),'created')
    rid=self.db.reports(-100)[0]['id']
    code,res=self.route(f'reports/{rid}/warn','POST',{})
    self.assertEqual(code,200)
    self.assertTrue(res['warning_recorded'])
    self.assertEqual(self.db.get_warn(-100,72),1)
    self.assertEqual(self.route(f'reports/{rid}/warn','POST',{})[0],409)
    self.assertEqual(self.db.get_warn(-100,72),1)
  def test_warn_admin_prohibited(self):
    self.api.admins={51,72};self.db.report(-100,99,72,9)
    rid=self.db.reports(-100)[0]['id']
    self.assertEqual(self.route(f'reports/{rid}/warn','POST',{})[0],403)
    self.assertEqual(self.db.get_warn(-100,72),0)
    self.assertEqual(self.db.get_report(rid,-100)['status'],'open')
  def test_warn_when_telegram_send_fails_is_not_duplicated(self):
    self.api.fail_send=True;self.db.report(-100,99,72,10)
    rid=self.db.reports(-100)[0]['id']
    code,res=self.route(f'reports/{rid}/warn','POST',{})
    self.assertEqual(code,200)
    self.assertFalse(res['notification_sent'])
    self.assertEqual(self.db.get_warn(-100,72),1)
  def test_invalid_group_id_fails(self):
    self.assertEqual(self.app.process('GET','/api/chats/100/analytics',self.login)[0],404)
if __name__=='__main__':unittest.main()
