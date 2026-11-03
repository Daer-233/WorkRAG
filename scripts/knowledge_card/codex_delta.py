"""Optional hook for the installed CodexAgent; keeps original permission logic.

Incremental notifications previously had no `item` object and were ignored.
All state is attached to one app-server client/run, never a shared global cache.
"""
from .model import packets

KEY = 'work_knowledge_card_v1'


def install(client_class, runner_class=None, result_class=None):
    if runner_class is not None and not getattr(runner_class,'_work_card_runner_installed',False):
        install_runner(runner_class,result_class)
    if getattr(client_class, '_work_card_installed', False):
        return
    raw_handler = client_class.handle_raw_notification
    item_handler = client_class.handle_item_notification
    emit = client_class.emit_text

    async def status(self, stage):
        self._work_stage = stage
        self.sequence += 1
        await self.events.put({'type':'message.delta','sequence':self.sequence,'data':{'chunk':{
            'role':'assistant','content':'','all_content':''.join(self.final_parts),
            'msg_sequence':self.sequence,'provider_specific_fields':{KEY:{
                'stage':stage,'packets':getattr(self,'_work_packets',[]),'status_only':True}}}}})

    async def emit_text(self, text, *, is_final=False):
        # Queue facade adds metadata without changing upstream emit/finish logic.
        queue = self.events
        class Queue:
            def __getattr__(_, name):
                return getattr(queue, name)
            async def put(_, event):
                chunk = event.get('data',{}).get('chunk')
                if chunk is not None:
                    chunk.setdefault('provider_specific_fields', {})[KEY] = {
                        'stage':'generating'}
                await queue.put(event)
        self.events = Queue()
        try:
            await emit(self,text,is_final=is_final)
        finally:
            self.events = queue

    async def raw(self, method, params):
        if method == 'turn/started':
            await status(self,'processing')
        if method == 'item/agentMessage/delta':
            item_id, delta = params.get('itemId'), params.get('delta')
            if not item_id or not isinstance(delta,str) or not delta:
                return
            if item_id in self.seen_agent_message_item_ids:
                return
            if not hasattr(self,'_work_prefixes'): self._work_prefixes = {}
            if item_id not in self._work_prefixes:
                self._work_prefixes[item_id] = list(self.final_parts)
            # Provider tokens may repeat (e.g. 哈 + 哈). The upstream emit
            # method deduplicates whole messages and must not process tokens.
            self.final_parts.append(delta)
            if self.streaming:
                self.sequence += 1
                await self.events.put({'type':'message.delta','sequence':self.sequence,'data':{'chunk':{
                    'role':'assistant','content':delta,'all_content':''.join(self.final_parts),
                    'msg_sequence':self.sequence,'provider_specific_fields':{KEY:{'stage':'generating'}}}}})
            return
        await raw_handler(self,method,params)

    async def item(self, method, params):
        value = params.get('item') or {}
        if method == 'item/started' and value.get('type') == 'agentMessage' and value.get('phase') == 'final_answer':
            # Final answer replaces progress commentary, including while it streams.
            self.final_parts = []
        tool = str(value.get('tool') or '')
        is_retrieval = value.get('type') == 'mcpToolCall' and (
            tool == 'langbot_retrieve_knowledge' or tool.endswith('__langbot_retrieve_knowledge'))
        if is_retrieval and method == 'item/started':
            await status(self,'retrieving')
        if is_retrieval and method == 'item/completed':
            results = packets(value.get('result',{}))
            existing = getattr(self,'_work_packets',[])
            by_id = {p.get('id'):p for p in existing + results}
            self._work_packets = list(by_id.values())[:24]
            await status(self,'generating')
        item_id = value.get('id')
        if method == 'item/completed' and value.get('type') == 'agentMessage':
            prefix = getattr(self,'_work_prefixes',{}).pop(item_id,None)
            if prefix is not None:
                # Authoritative snapshot replaces deltas for the same item.
                self.final_parts = prefix
        await item_handler(self,method,params)

    client_class.handle_raw_notification = raw
    client_class.handle_item_notification = item
    client_class.emit_text = emit_text
    client_class._work_card_installed = True
def install_runner(runner_class,result_class):
        run = runner_class.run
        async def wrapped(self,ctx):
            yield result_class.model_validate({'run_id':ctx.run_id,'type':'message.delta','data':{'chunk':{
                'role':'assistant','content':'正在处理…','all_content':'正在处理…',
                'provider_specific_fields':{KEY:{'stage':'processing','status_only':True}}}}})
            latest = {}
            async for result in run(self,ctx):
                data = result.data
                if isinstance(data,dict):
                    chunk = data.get('chunk') or data.get('message')
                    if isinstance(chunk,dict):
                        info = (chunk.get('provider_specific_fields') or {}).get(KEY)
                        if info:
                            retained = latest.get('packets')
                            latest = dict(info)
                            if retained and 'packets' not in latest: latest['packets'] = retained
                        elif latest:
                            # Status-only applies to that event, never the final answer.
                            chunk.setdefault('provider_specific_fields',{})[KEY] = {
                                k:v for k,v in latest.items() if k != 'status_only'}
                if getattr(result.type,'value',result.type) == 'run.failed':
                    yield result_class.model_validate({'run_id':ctx.run_id,'type':'message.delta','data':{'chunk':{
                        'role':'assistant','content':'','provider_specific_fields':{KEY:{**latest,'stage':'failed','status_only':True}}}}})
                yield result
        runner_class.run = wrapped
        runner_class._work_card_runner_installed = True
