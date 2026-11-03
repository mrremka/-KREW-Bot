import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from krew.db import Database
from krew.web import verify_init_data, WebError, Application

TOKEN="TEST:abcdefghijklmnopqrstuvwxyz"

def signed(uid=123, ts=None, **extra):
    payload={"auth_date":str(int(time.time()) if ts is None else ts),"user":json.dumps({"id":uid,"first_name":"Иван"},ensure_ascii=False,separators=(",",":")),**extra}
    s="\n".join(f"{k}={v}" for k,v in sorted(payload.items()))
    key=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
    payload["hash"]=hmac.new(key,s.encode(),hashlib.sha256).hexdigest()
    return urlencode(payload)

class FakeAPI:
    def __init__(self): self.admins={123};self.calls=[]
    def call(self,method,**kw):
        self.calls.append((method,kw))
        if method=="getChatMember": return {"status":"administrator" if kw["user_id"] in self.admins else "member"}
        raise AssertionError(method)

class MiniAppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"krew.sqlite3"
        self.db=Database(self.path)
        self.db.ensure_chat(-100,"Основной")
        self.db.ensure_chat(-200,"Вторая")
        self.db.close()
        self.fake=FakeAPI()
        self.app=Application(TOKEN,self.path,api=self.fake)
        self.auth="tma "+signed()
    def tearDown(self): self.temp.cleanup()

    def test_valid_signature(self):
        self.assertEqual(verify_init_data(signed(),TOKEN)["id"],123)
    def test_tampered_id_rejected(self):
        with self.assertRaises(WebError): verify_init_data(signed().replace("123","999"),TOKEN)
    def test_expired_and_future_rejected(self):
        for offset in (-3700,100):
            with self.assertRaises(WebError):verify_init_data(signed(ts=int(time.time())+offset),TOKEN)
    def test_duplicate_params_rejected(self):
        with self.assertRaises(WebError):verify_init_data(signed()+"&auth_date=1",TOKEN)
    def test_reject_no_init_data(self):
        self.assertEqual(self.app.process("GET","/api/chats")[0],401)
    def test_chat_admin_access_control(self):
        r=self.app.process("GET","/api/chats/-100/overview",self.auth)
        self.assertEqual(r[0],200)
        self.fake.admins.clear()
        self.assertEqual(self.app.process("GET","/api/chats/-100/overview",self.auth)[0],403)
    def test_unknown_room_does_not_get_created(self):
        self.assertEqual(self.app.process("GET","/api/chats/-999/overview",self.auth)[0],404)
        db=Database(self.path)
        self.assertIsNone(db.known_chat(-999))
        db.close()
    def test_all_chats_checked(self):
        status,data=self.app.process("GET","/api/chats",self.auth)
        self.assertEqual(status,200)
        self.assertEqual(len(data["chats"]),2)
    def test_settings_are_validated_and_audited(self):
        b="/api/chats/-100/settings"
        self.assertEqual(self.app.process("PATCH",b,self.auth,{"field":"captcha","value":True})[0],200)
        self.assertEqual(self.app.process("PATCH",b,self.auth,{"field":"captcha","value":"true"})[0],400)
        self.assertEqual(self.app.process("PATCH",b,self.auth,{"field":"is_admin","value":True})[0],400)
        self.assertEqual(self.app.process("PATCH",b,self.auth,{"field":"warn_limit","value":999})[0],400)
        db=Database(self.path)
        self.assertTrue(db.get_chat(-100)["captcha"])
        self.assertFalse(db.get_chat(-200)["captcha"])
        self.assertEqual(len(db.audit(-100)),1)
        db.close()
    def test_close_report_once(self):
        db=Database(self.path)
        self.assertEqual(db.report(-100,22,31,55),"created")
        rid=db.reports(-100)[0]["id"]
        db.close()
        ep=f"/api/chats/-100/reports/{rid}/close"
        self.assertEqual(self.app.process("POST",ep,self.auth,{})[0],200)
        self.assertEqual(self.app.process("POST",ep,self.auth,{})[0],409)
    def test_migrate_original_02_db(self):
        db=Database(self.path)
        db.track(-100,"messages",5)
        self.assertEqual(db.timeline(-100)[-1]["messages"],5)
        db.close()

if __name__=="__main__":unittest.main()
