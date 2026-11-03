import asyncio
from copy import deepcopy
from knowledge_codex_model import install


def test_luna_resume_overrides_model_effort_only():
    class Client:
        def __init__(self): self.calls=[]
        async def initialize(self): self.initialized=True
        async def request(self,method,params=None):
            self.calls.append((method,deepcopy(params)))
            if method=='config/read': return {'config':{'model':'gpt-6-luna','model_reasoning_effort':'high'}}
            return params
    install(Client);install(Client)
    async def run():
        client=Client();await client.initialize()
        params={'threadId':'existing','model':None,'approvalPolicy':'on-request','sandbox':'workspace-write',
                'config':{'unrelated':True}}
        original=deepcopy(params)
        result=await client.request('thread/resume',params)
        assert result['model']=='gpt-6-luna' and result['config']['model_reasoning_effort']=='high'
        assert result['approvalPolicy']=='on-request' and result['sandbox']=='workspace-write'
        assert result['config']['unrelated'] is True and params==original
        assert len([c for c in client.calls if c[0]=='config/read'])==1
    asyncio.run(run())


def test_other_models_and_non_thread_requests_unchanged():
    class Client:
        async def initialize(self): pass
        async def request(self,method,params=None):
            if method=='config/read': return {'config':{'model':'gpt-6.1-terra','model_reasoning_effort':'medium'}}
            return params
    install(Client)
    async def run():
        client=Client();await client.initialize()
        params={'threadId':'existing','model':None}
        assert await client.request('thread/resume',params) is params
        client._work_luna_model='gpt-6-luna';client._work_luna_effort='high'
        assert await client.request('turn/start',params) is params
    asyncio.run(run())


def test_work_assistant_explicitly_pins_terra_medium_on_resume():
    class Client:
        async def initialize(self):pass
        async def request(self,method,params=None):
            if method=='config/read':return {'config':{'model':'gpt-6.1-terra','model_reasoning_effort':'medium'}}
            return params
    install(Client,allowed_models=('gpt-6.1-terra',))
    async def run():
        client=Client();await client.initialize()
        result=await client.request('thread/resume',{'threadId':'previous-luna-thread','model':'gpt-6-luna',
            'approvalPolicy':'on-request','sandbox':'read-only'})
        assert result['model']=='gpt-6.1-terra' and result['config']['model_reasoning_effort']=='medium'
        assert result['approvalPolicy']=='on-request' and result['sandbox']=='read-only'
    asyncio.run(run())
