"""Real Pi worker + installed SDK, with explicit fake provider/MCP I/O."""
import asyncio
import json
import sys
import unittest
import httpx
from langbot_plugin.api.entities.builtin.provider.message import LLMStreamEvent
from workrag_agent.pi_model import PiModel

CONFIG=json.load(sys.stdin)
REF={'entry_id':'00000000-0000-0000-0000-000000000001','title':'测试流程','version':'v1'}
STATE={'question':'测试问题','_run_scope':'test-scope','_allowed_entries':[REF['entry_id']], '_max_calls':2,'_top_k':5}
def event(text='',call=None):
    return LLMStreamEvent.model_validate({'chunk':{'role':'assistant','content':text,'tool_calls':call}})
def tool(index):return event(call=[{'id':'c'+str(index),'type':'function','function':{'name':'search_knowledge','arguments':'{"query":"test"}'}}])

class API:
    def __init__(self,batches,fail=False):self.batches=iter(batches);self.called=0;self.fail=fail;self.owner=None
    async def invoke_llm_stream_events(self,uuid,messages,funcs,remove_think=None):
        assert asyncio.current_task() is self.owner and uuid=='selected-model' and remove_think
        for value in next(self.batches):yield value
    async def call_tool(self,name,args):
        assert asyncio.current_task() is self.owner and args['run_scope']=='test-scope'
        assert 'identity' not in args;self.called+=1
        if self.fail:raise PermissionError('mock refusal')
        return {'status':'ok','results':[{'content':'测试流程 e1','metadata':{'result_type':'source_evidence',**REF,'steps':[{'evidence_ids':['e1']}]}}]}
class Backend:
    def valid_refs(self,refs):return bool(refs)

class Tests(unittest.IsolatedAsyncioTestCase):
    async def run_model(self,api,question='测试问题'):
        api.owner=asyncio.current_task()
        model=PiModel(api,'selected-model',{'search_knowledge':'granted_search_knowledge'},Backend(),CONFIG['url'],CONFIG['token'])
        events=[e async for e in model.events([{'role':'system','content':'测试助手'},{'role':'user','content':question}],{**STATE,'question':question})]
        return events[-1]['value'],events
    async def test_daily_and_real_provider_incremental_forwarding(self):
        value,events=await self.run_model(API([[event('{"intent":"daily"}')],[event('你'),event('好')]]))
        self.assertEqual(value['content'],'你好');self.assertEqual([e['content'] for e in events if e['type']=='answer_delta'],['你','你好'])
    async def test_pi_tool_loop_then_grounded_final_answer(self):
        api=API([[event('{"intent":"knowledge"}')],[tool(1)],[event('测试流程 e1')],[event('已核实'),event('操作步骤')]])
        value,events=await self.run_model(api)
        self.assertEqual(api.called,1);self.assertEqual(value['_pi_state']['refs'][0]['entry_id'],REF['entry_id'])
        self.assertIn('资料来源',value['content']);self.assertIn('操作步骤',value['content'])
    async def test_call_limit_is_enforced_by_pi_and_python(self):
        api=API([[event('{"intent":"knowledge"}')],[tool(1)],[tool(2)],[tool(3)]])
        value,_=await self.run_model(api)
        self.assertTrue(value['_pi_limited']);self.assertEqual(api.called,2)
    async def test_tool_failure_remains_visible_to_graph(self):
        api=API([[event('{"intent":"knowledge"}')],[tool(1)],[event('权限拒绝')]],fail=True)
        value,_=await self.run_model(api)
        self.assertEqual(value['_pi_state']['tool_errors'],['permission_denied']);self.assertFalse(value['_pi_state']['refs'])
    async def test_two_concurrent_requests_are_isolated(self):
        async def one(name):return await self.run_model(API([[event('{"intent":"daily"}')],[event(name)]]),name)
        a,b=await asyncio.gather(one('alice'),one('bob'))
        self.assertEqual(a[0]['content'],'alice');self.assertEqual(b[0]['content'],'bob')

    async def test_provider_error_is_not_reported_as_success(self):
        api=API([[event('{"intent":"daily"}')]])
        with self.assertRaises(RuntimeError):await self.run_model(api)

    async def test_cancellation_closes_provider_and_pi_request(self):
        entered=asyncio.Event();closed=asyncio.Event()
        class Slow(API):
            async def invoke_llm_stream_events(inner,uuid,messages,funcs,remove_think=None):
                assert asyncio.current_task() is inner.owner
                if not entered.is_set():
                    entered.set();yield event('{"intent":"daily"}');return
                try:await asyncio.sleep(300)
                finally:closed.set()
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.run_model(Slow([])),timeout=.3)
        self.assertTrue(closed.is_set())
        url=CONFIG['url'].replace('ws://','http://').replace('/run','/health')
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(30):
                active=(await client.get(url)).json()['active']
                if active==0:break
                await asyncio.sleep(.05)
        self.assertEqual(active,0)

if __name__=='__main__':unittest.main()
