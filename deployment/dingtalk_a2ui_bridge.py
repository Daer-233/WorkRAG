"""Opt-in A2UI text-card transport for LangBot's existing DingTalk client.

Loaded only after explicit deployment. Native attachments remain native;
card media resources and action callbacks are separate integration work.
"""
import copy
import json
from pathlib import Path
from uuid import uuid4

CONFIG=Path('/app/data/workrag-a2ui-config.json')
TEMPLATE=Path('/app/data/workrag-a2ui-template.json')


def wire(messages):return [json.dumps(m,ensure_ascii=False) for m in messages]

def enabled_for_config(config):
    options=json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    return options.get('enabled') is True and options.get('client_id')==config.get('client_id')


class A2UITransport:
    def __init__(self,client,template):self.client,self.template=client,template

    async def request(self,method,path,payload):
        if not await self.client.check_access_token():await self.client.get_access_token()
        async with self.client._http_client_context() as http:
            response=await http.request(method,'https://api.dingtalk.com'+path,
                headers={'x-acs-dingtalk-access-token':self.client.access_token},json=payload,timeout=30)
        value=response.json()
        if response.status_code!=200 or value.get('success') is not True:
            code=value.get('code') or value.get('errorCode') or 'unknown'
            raise RuntimeError('A2UI request failed: HTTP '+str(response.status_code)+'; code='+str(code))
        deliveries=value.get('result',{}).get('deliverResults',[])
        if any(item.get('success') is not True for item in deliveries):
            raise RuntimeError('A2UI target delivery rejected')
        try:
            import time
            with Path('/app/data/workrag-a2ui-events.jsonl').open('a') as log:
                log.write(json.dumps({'time':time.time(),'method':method,'track':payload.get('outTrackId'),
                    'flow':payload.get('flowStatus'),'http_status':response.status_code,
                    'accepted':True,'message_count':len(payload.get('a2uiMessages',[]))})+'\n')
        except OSError:pass
        return value

    async def create(self,incoming):
        if str(incoming.conversation_type)!='1':raise PermissionError('Private test conversation required')
        sid='workrag-'+uuid4().hex;messages=copy.deepcopy(self.template)
        for message in messages:
            for kind in ('createSurface','updateDataModel','updateComponents'):
                if kind in message:message[kind]['surfaceId']=sid
        await self.request('POST','/v1.0/card/ai/instances/createAndDeliver',{
            'outTrackId':sid,'openSpaceId':'dtv1.card//im_robot.'+incoming.sender_staff_id,
            'protocolVersion':'1.0','userIdType':1,'flowStatus':'PROCESSING',
            'a2uiMessages':wire(messages),'summary':'工作知识助手',
            'imRobotOpenSpaceModel':{'supportForward':False},
            'imRobotOpenDeliverModel':{'robotCode':self.client.key},
            'a2uiAnnotations':[{'surfaceId':sid,'componentId':'answer','type':'artifact'}]})
        return {'workrag_a2ui':True,'surface_id':sid},sid

    async def update(self,card,track,text,final):
        sid=card['surface_id']
        def delta(path,value):return {'version':'v1.0','updateDataModel':{'surfaceId':sid,'path':path,'value':value}}
        changes=[delta('/status','回答完成' if final else '正在生成回答…'),
                 delta('/answer',text if final else '[AIGenerating]'+text)]
        # No disconnected controls are exposed. This update preserves the rest
        # of the card's data and the user's local collapse state.
        await self.request('PUT','/v1.0/card/ai/instances/update',{
            'outTrackId':track,'outUpdateId':uuid4().hex,
            'flowStatus':'FINISH' if final else 'INPUTTING','a2uiMessages':wire(changes)})


def install(client_class):
    if getattr(client_class,'_workrag_a2ui_installed',False):return
    original_create=client_class.create_and_card;original_update=client_class.send_card_message
    def config():
        return json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    async def create(self,temp_card_id,incoming_message,quote_origin=False,card_auto_layout=True):
        options=config()
        if (options.get('enabled') is True and options.get('client_id')==self.key and
            str(incoming_message.conversation_type)=='1' and
            incoming_message.sender_staff_id==options.get('private_tester')):
            return await A2UITransport(self,json.loads(TEMPLATE.read_text())).create(incoming_message)
        if not temp_card_id:
            return {'workrag_plain':True,'incoming':incoming_message},uuid4().hex
        return await original_create(self,temp_card_id,incoming_message,quote_origin,card_auto_layout)
    async def update(self,card_instance,card_instance_id,content,is_final):
        if isinstance(card_instance,dict) and card_instance.get('workrag_plain'):
            if is_final:return await self.send_message(content,card_instance['incoming'],[])
            return
        if isinstance(card_instance,dict) and card_instance.get('workrag_a2ui'):
            return await A2UITransport(self,[]).update(card_instance,card_instance_id,content,is_final)
        return await original_update(self,card_instance,card_instance_id,content,is_final)
    client_class.create_and_card=create;client_class.send_card_message=update
    client_class._workrag_a2ui_installed=True
