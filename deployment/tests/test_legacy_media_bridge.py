
# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import legacy_media_bridge as media
from langbot_plugin.api.entities.builtin.platform.message import Image,File,Plain,MessageChain

class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_images_stay_in_card_and_file_is_preserved(self):
        class Bot:
            params=None
            async def get_legacy_access_token(self):return 'mock'
            @asynccontextmanager
            async def _http_client_context(self):yield self
            async def post(self,*args,**kwargs):return None
            def _check_send_result(self,r):return {'media_id':'@mock-image'}
            async def update_card_data(self,**kwargs):self.params=kwargs['card_param_map'];return True
        class Adapter:
            config={'client_id':'app','card_template_id':'template'}
            bot=Bot();card_instance_id_dict={'reply':({},'card')}
            async def reply_message_chunk(self,source,bot_message,message,**kwargs):return message
        options={'client_id':'app','template_id':'template','private_tester':'owner','folded_template_published':True}
        source=SimpleNamespace(source_platform_object=SimpleNamespace(incoming_message=SimpleNamespace(sender_staff_id='owner')))
        message=MessageChain([Plain(text='资料'),Image(base64=base64.b64encode(b'png').decode()),File(name='demo.docx',base64='ZA==')])
        with patch.object(media,'settings',lambda:options),patch.object(media,'record',lambda x:None):
            media.install_adapter(Adapter);a=Adapter()
            result=await a.reply_message_chunk(source,SimpleNamespace(resp_message_id='reply',tool_calls=None),message,is_final=True)
            self.assertFalse(any(isinstance(p,Image) for p in result));self.assertTrue(any(isinstance(p,File) for p in result))
            self.assertEqual(a.bot.params['workrag_image_0'],'@mock-image')
            options['folded_template_published']=False
            result=await a.reply_message_chunk(source,SimpleNamespace(resp_message_id='reply',tool_calls=None),message,is_final=True)
            self.assertTrue(any(isinstance(p,Image) for p in result))
    async def test_platform_rejection_is_not_treated_as_file_success(self):
        class Bot:
            key='app'
            async def send_card_message(self,*args):return None
            async def send_attachment(self,*args):return {'invalidStaffIdList':['rejected']}
        options={'client_id':'app','private_tester':'owner'}
        with patch.object(media,'settings',lambda:options),patch.object(media,'record',lambda x:None):
            media.install_client(Bot)
            with self.assertRaisesRegex(RuntimeError,'not delivered'):
                await Bot().send_attachment(File(name='demo.docx',base64='ZA=='),SimpleNamespace(sender_staff_id='owner'))

    async def test_streaming_template_channel_is_populated_before_final_state(self):
        calls=[]
        class Bot:
            key='app'
            async def send_attachment(self,*args):return {}
            async def send_card_message(self,*args):calls.append('state')
            async def streaming_update_card(self,**kwargs):calls.append(kwargs);return True
        options={'client_id':'app','answer_streaming_component':True}
        with patch.object(media,'settings',lambda:options),patch.object(media,'record',lambda x:None):
            media.install_client(Bot)
            await Bot().send_card_message({},'existing-card','visible answer',True)
        self.assertEqual(calls[0]['content_key'],'answer');self.assertEqual(calls[0]['content_value'],'visible answer')
        self.assertTrue(calls[0]['finished']);self.assertEqual(calls[1],'state')

    async def test_existing_mixed_template_stays_visible_without_double_writing_deltas(self):
        calls=[]
        class Bot:
            key='app';variables='';stream='';visible=''
            async def send_attachment(self,*args):return {}
            async def send_card_message(self,card,track,content,final):
                calls.append(('variables',final));self.variables=content
                self.visible=self.stream if final else self.variables
            async def streaming_update_card(self,**kwargs):
                calls.append(('stream',kwargs['finished']));self.stream=kwargs['content_value'];return True
        options={'client_id':'app','answer_streaming_component':True}
        with patch.object(media,'settings',lambda:options),patch.object(media,'record',lambda x:None):
            media.install_client(Bot);bot=Bot()
            await bot.send_card_message({},'card','第一段',False)
            self.assertEqual(bot.visible,'第一段')
            await bot.send_card_message({},'card','第一段第二段',False)
            self.assertEqual(bot.visible,'第一段第二段')
            self.assertEqual(calls,[('variables',False),('variables',False)])
            await bot.send_card_message({},'card','完整回答',True)
            self.assertEqual(bot.visible,'完整回答')
            self.assertEqual(calls[-2:],[('stream',True),('variables',True)])

    async def test_failed_final_stream_does_not_switch_to_blank_completed_state(self):
        calls=[]
        class Bot:
            key='app'
            async def send_attachment(self,*args):return {}
            async def send_card_message(self,*args):calls.append('state')
            async def streaming_update_card(self,**kwargs):return False
        with patch.object(media,'settings',lambda:{'client_id':'app','answer_streaming_component':True}):
            media.install_client(Bot)
            with self.assertRaisesRegex(RuntimeError,'streaming-answer channel'):
                await Bot().send_card_message({},'card','完整回答',True)
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
