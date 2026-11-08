import base64
import hashlib
import hmac
import json
import time


def identity_key(identity):
    required=('workspace','bot','processor','conversation','sender')
    if any(not isinstance(identity.get(k),str) or not identity[k] for k in required):
        raise ValueError('Missing trusted conversation identity')
    return hashlib.sha256(json.dumps({k:identity[k] for k in required},sort_keys=True).encode()).hexdigest()


def actor_key(identity):
    return hashlib.sha256(json.dumps([identity['workspace'],identity['sender']]).encode()).hexdigest()


def issue_scope(secret, identity, entries, run_id, ttl=180):
    identity_key(identity)
    body=base64.urlsafe_b64encode(json.dumps({'identity':identity,'entries':sorted(set(entries)),
        'run_id':run_id,'exp':int(time.time())+ttl},separators=(',',':')).encode()).decode().rstrip('=')
    signature=hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+signature


def verify_scope(secret, token):
    try:
        body,signature=token.rsplit('.',1)
        expected=hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected): raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if data['exp']<=time.time(): raise ValueError()
        identity_key(data['identity'])
        if not isinstance(data['entries'],list): raise ValueError()
        return data
    except (ValueError,KeyError,TypeError):
        raise PermissionError('Invalid or expired run scope') from None
