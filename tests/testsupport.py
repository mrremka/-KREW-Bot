import hashlib,hmac,json,time
from urllib.parse import urlencode

class DummyAPI:
    def __init__(self): self.calls=[]
    def call(self, method, **data):
        self.calls.append((method,data))
        if method=='getChatMember': return {'status':'administrator' if data['user_id']==1 else 'member'}
        if method=='sendMessage': return {'message_id':101}
        return True

def msg(user_id,text,reply_to=None,chat=-100):
    m={'message_id':33,'chat':{'type':'supergroup','id':chat,'title':'Test'},'from':{'id':user_id,'first_name':'Test'},'text':text}
    if reply_to: m['reply_to_message']={'from':{'id':reply_to,'first_name':'User'}}
    return m

def signed_auth(token, user_id):
    p={'auth_date':str(int(time.time())),'user':json.dumps({'id':user_id},separators=(',',':'))}
    check='\n'.join(f'{k}={v}' for k,v in sorted(p.items()))
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    p['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return 'tma '+urlencode(p)
