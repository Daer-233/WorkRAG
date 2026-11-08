"""Run with the actual installed langbot-plugin SDK; all provider I/O is mocked."""
import asyncio
import json
import unittest
from langbot_plugin.api.entities.builtin.provider.message import LLMStreamEvent,Message
from workrag_agent.model import LangBotModel

def event(content='',tool_calls=None):
    return LLMStreamEvent.model_validate({'chunk':{'role':'assistant','content':content,'tool_calls':tool_calls}})

class API:
    def __init__(self,batches):self.batches=iter(batches);self.calls=[]
    async def invoke_llm_stream_events(self,uuid,messages,funcs,remove_think=None):
        assert uuid=='selected-model' and all(isinstance(m,Message) for m in messages)
        assert remove_think is True
        self.calls.append((messages,funcs))
        for item in next(self.batches): yield item

class ModelCheck(unittest.IsolatedAsyncioTestCase):
    async def test_daily_route_and_text_stream(self):
        api=API([[event('{"intent":"daily"}')],[event('你'),event([{'type':'text','text':'好'}])]])
        result=await LangBotModel(api,'selected-model',{})([{'role':'system','content':'助手'},{'role':'user','content':'你好'}],{'question':'你好'})
        self.assertEqual(result['content'],'你好');self.assertFalse(result['requires_evidence'])
        self.assertEqual(len(api.calls),2);self.assertEqual(api.calls[1][1],[])

    async def test_tool_stream_and_following_evidence_answer(self):
        def tc(args):return [{'id':'call-1','type':'function','function':{'name':'search_knowledge','arguments':args}}]
        api=API([[event('{"intent":"knowledge"}')],[event(tool_calls=tc('{"query":')),event(tool_calls=tc('"试用期"}'))],
                 [event('依据来源 A [e1]。')]])
        model=LangBotModel(api,'selected-model',{'search_knowledge':'search_knowledge'})
        messages=[{'role':'system','content':'助手'},{'role':'user','content':'试用期制度'}]
        result=await model(messages,{'question':'试用期制度'})
        self.assertEqual(result['tool_calls'][0]['arguments'],{'query':'试用期'})
        self.assertEqual(api.calls[1][1][0].name,'search_knowledge')
        second=await model(messages+[{'role':'assistant','content':'','tool_calls':tc('{"query":"试用期"}')},
                          {'role':'tool','tool_call_id':'call-1','content':'{"status":"ok"}'}],{'question':'试用期制度','intent':result['intent']})
        self.assertIn('[e1]',second['content']);self.assertEqual(len(api.calls),3)

    async def test_complete_tool_snapshots_do_not_duplicate_json(self):
        calls=[{'id':'call-1','type':'function','function':{'name':'search_knowledge','arguments':'{"query":"制度"}'}}]
        api=API([[event(tool_calls=calls),event(tool_calls=calls)]])
        result=await LangBotModel(api,'selected-model',{'search_knowledge':'search_knowledge'})(
            [{'role':'system','content':'助手'},{'role':'user','content':'制度'}],{'question':'制度','intent':'knowledge'})
        self.assertEqual(result['tool_calls'][0]['arguments'],{'query':'制度'})

    async def test_reasoning_fields_preserved_for_tool_protocol_not_final_text(self):
        reasoning=LLMStreamEvent.model_validate({'chunk':{'role':'assistant','provider_specific_fields':{'reasoning_content':'private protocol context'}}})
        call=event(tool_calls=[{'id':'call-1','type':'function','function':{'name':'search_knowledge','arguments':'{"query":"制度"}'}}])
        model=LangBotModel(API([[reasoning,call]]),'selected-model',{'search_knowledge':'search_knowledge'})
        result=await model([{'role':'system','content':'助手'},{'role':'user','content':'制度'}],{'question':'制度','intent':'knowledge'})
        self.assertEqual(result['content'],'')
        self.assertEqual(result['provider_specific_fields']['reasoning_content'],'private protocol context')

    async def test_empty_stream_is_model_error(self):
        model=LangBotModel(API([[]]),'selected-model',{})
        with self.assertRaisesRegex(ValueError,'no text'):
            await model([{'role':'system','content':'助手'},{'role':'user','content':'你好'}],{'question':'你好','intent':'daily'})

    async def test_public_stream_omits_router_and_tool_planning(self):
        calls=[{'id':'call-1','type':'function','function':{'name':'search_knowledge','arguments':'{"query":"制度"}'}}]
        api=API([[event('{"intent":"knowledge"}')],[event('内部计划'),event(tool_calls=calls)]])
        events=[e async for e in LangBotModel(api,'selected-model',{'search_knowledge':'search_knowledge'}).events(
            [{'role':'system','content':'助手'},{'role':'user','content':'制度'}],{'question':'制度'})]
        self.assertEqual([e['type'] for e in events],['model_result'])
        self.assertEqual(events[-1]['value']['tool_calls'][0]['name'],'search_knowledge')

    async def test_grounded_answer_stream_is_a_tool_free_generation(self):
        api=API([[event('测试资料 [e1]：未公开的回答草稿')],[event('步骤一'),event('，点击确认。')]])
        state={'question':'操作','intent':'knowledge','stream_grounded':True,
               'refs':[{'title':'测试资料','version':'v1','evidence_ids':['e1']}]}
        events=[e async for e in LangBotModel(api,'selected-model',{'search_knowledge':'search_knowledge'}).events(
            [{'role':'system','content':'助手'},{'role':'user','content':'操作'}],state)]
        deltas=[e['content'] for e in events if e['type']=='answer_delta']
        self.assertEqual(len(deltas),2)
        self.assertIn('测试资料',deltas[0]);self.assertIn('步骤一',deltas[0])
        self.assertNotIn('点击确认',deltas[0]);self.assertIn('点击确认',deltas[1])
        self.assertNotIn('回答草稿',''.join(deltas));self.assertEqual(api.calls[-1][1],[])

    async def test_daily_tokens_are_forwarded_as_they_arrive(self):
        api=API([[event('{"intent":"daily"}')],[event('你'),event('好')]])
        events=[e async for e in LangBotModel(api,'selected-model',{}).events(
            [{'role':'system','content':'助手'},{'role':'user','content':'你好'}],{'question':'你好'})]
        self.assertEqual([e['content'] for e in events if e['type']=='answer_delta'],['你','你好'])

if __name__=='__main__':unittest.main()
