"""Execute Host RPC on the owning Runner task, not LangGraph's child tasks."""
import asyncio
import inspect
from contextlib import suppress

class InvocationBridge:
    def __init__(self): self.queue=asyncio.Queue(); self.active=True

    async def call(self,function,*args):
        if not self.active: raise RuntimeError('Invocation ended')
        future=asyncio.get_running_loop().create_future()
        await self.queue.put((function,args,future))
        return await future

    async def run(self,awaitable):
        iterator=self.iterate(awaitable)
        try:
            async for event in iterator:
                if event['type']=='workflow_result': return event['value']
        finally: await iterator.aclose()

    async def iterate(self,awaitable):
        graph=asyncio.create_task(awaitable)
        owner=asyncio.current_task()
        rpc_active=False
        deadline_interrupt=False
        def graph_completed(_):
            nonlocal deadline_interrupt
            # A timed-out graph can finish while its original Runner task is
            # still awaiting Host RPC. Cancel that await on the owning task.
            if rpc_active and not owner.done():
                deadline_interrupt=True
                owner.cancel()
        graph.add_done_callback(graph_completed)
        pending=None
        try:
            while not graph.done():
                pending=asyncio.create_task(self.queue.get())
                done,_=await asyncio.wait({graph,pending},return_when=asyncio.FIRST_COMPLETED)
                if pending not in done:
                    pending.cancel()
                    with suppress(asyncio.CancelledError): await pending
                    break
                function,args,future=pending.result()
                if future.cancelled(): continue
                try:
                    rpc_active=True
                    value=function(*args)
                    if inspect.isasyncgen(value):
                        iterator=value; value=None
                        try:
                            async for event in iterator:
                                if event['type']=='model_result': value=event['value']
                                else: yield event
                        finally: await iterator.aclose()
                    else: value=await value
                    if not future.done(): future.set_result(value)
                except asyncio.CancelledError:
                    if deadline_interrupt:
                        deadline_interrupt=False
                        owner.uncancel()
                        if owner.cancelling(): raise
                        yield {'type':'workflow_result','value':await graph}
                        return
                    raise
                except Exception as error:
                    if not future.done(): future.set_exception(error)
                finally: rpc_active=False
            yield {'type':'workflow_result','value':await graph}
        finally:
            self.active=False
            graph.remove_done_callback(graph_completed)
            if pending and not pending.done(): pending.cancel()
            if not graph.done(): graph.cancel()
            with suppress(asyncio.CancelledError): await graph
            while not self.queue.empty():
                _,_,future=self.queue.get_nowait()
                if not future.done(): future.cancel()
