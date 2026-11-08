"""Offline transport tests: no credentials, network or actual messages."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import dingtalk_a2ui_bridge as bridge
from dingtalk_a2ui_bridge import A2UITransport
from build_dingtalk_json_card import messages

class Client:
    key='mock-app'
    access_token='mock-token'
    status=200
    value={'success':True,'result':{'deliverResults':[{'success':True}]}}
    def __init__(self):self.calls=[]
    async def check_access_token(self):return True
    @asynccontextmanager
    async def _http_client_context(self):yield self
    async def request(self,method,path,**kwargs):
        self.calls.append((method,path,kwargs['json']))
        return SimpleNamespace(status_code=self.status,json=lambda:self.value)

class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_keeps_surface_and_deltas_preserve_data(self):
        client=Client();api=A2UITransport(client,messages())
        card,track=await api.create(SimpleNamespace(conversation_type='1',sender_staff_id='mock-owner'))
        await api.update(card,track,'第一段',False);await api.update(card,track,'完整正文',True)
        create,stream,final=[c[2] for c in client.calls]
        self.assertIsInstance(create['a2uiMessages'][0],str)
        self.assertEqual(stream['flowStatus'],'INPUTTING');self.assertEqual(final['flowStatus'],'FINISH')
        self.assertEqual(stream['outTrackId'],track);self.assertNotEqual(stream['outUpdateId'],final['outUpdateId'])
        for raw in stream['a2uiMessages']+final['a2uiMessages']:
            msg=json.loads(raw);self.assertNotIn('createSurface',msg)
            self.assertEqual(msg['updateDataModel']['surfaceId'],track)
        self.assertNotIn('[AIGenerating]',final['a2uiMessages'][-1])
    async def test_permission_failure_does_not_claim_creation(self):
        client=Client();client.status=403;client.value={'code':'AccessDenied'}
        with self.assertRaisesRegex(RuntimeError,'403'):
            await A2UITransport(client,messages()).create(SimpleNamespace(conversation_type='1',sender_staff_id='mock-owner'))
    async def test_per_target_rejection_and_group_are_rejected(self):
        client=Client();client.value={'success':True,'result':{'deliverResults':[{'success':False}]}}
        api=A2UITransport(client,messages())
        with self.assertRaisesRegex(RuntimeError,'delivery rejected'):
            await api.create(SimpleNamespace(conversation_type='1',sender_staff_id='mock-owner'))
        with self.assertRaises(PermissionError):await api.create(SimpleNamespace(conversation_type='2'))

    async def test_capability_without_legacy_template_and_other_user_fallback(self):
        config=SimpleNamespace(is_file=lambda:True,read_text=lambda:json.dumps({'enabled':True,'client_id':'mock-app','private_tester':'owner'}))
        class Fake(Client):
            async def create_and_card(self,*args):return 'legacy'
            async def send_card_message(self,*args):return 'legacy-update'
            async def send_message(self,text,incoming,at):return text
        with patch.object(bridge,'CONFIG',config):
            self.assertTrue(bridge.enabled_for_config({'client_id':'mock-app','card_template_id':''}))
            self.assertFalse(bridge.enabled_for_config({'client_id':'different'}))
            bridge.install(Fake);client=Fake()
            incoming=SimpleNamespace(conversation_type='1',sender_staff_id='different-user')
            card,track=await client.create_and_card('',incoming)
            self.assertTrue(card['workrag_plain']);self.assertFalse(client.calls)
            self.assertIsNone(await client.send_card_message(card,track,'partial',False))
            self.assertEqual(await client.send_card_message(card,track,'final',True),'final')

if __name__=='__main__':unittest.main()
