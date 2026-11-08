"""Local read-only WorkRAG MCP. Both access authentication and signed run scope required."""
import asyncio
import hmac
import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount,Route
from .store import Store
from .tools import Backend,ToolService

mcp=FastMCP('WorkRAGReadOnly',stateless_http=True,json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                allowed_hosts=['127.0.0.1:*','localhost:*','host.docker.internal:8061'],
                allowed_origins=['http://127.0.0.1:*','http://localhost:*']))
store=Store(os.environ['WORKRAG_AGENT_DSN'])
service=ToolService(store,Backend(),os.environ['WORKRAG_SCOPE_SECRET'])

async def invoke(name,args,scope):
    try: return await asyncio.to_thread(service.call,name,args,scope)
    except PermissionError: return {'status':'permission_denied','results':[]}
    except ValueError as e: return {'status':'invalid_request','message':str(e),'results':[]}
    except Exception: return {'status':'tool_error','message':'检索服务暂时不可用，请稍后重试。','results':[]}

@mcp.tool()
async def search_knowledge(query:str,run_scope:str,top_k:int=5)->dict:
    """检索已发布资料。run_scope 仅由受信 Runner 注入，模型不得生成。"""
    return await invoke('search_knowledge',{'query':query,'top_k':top_k},run_scope)

@mcp.tool()
async def get_document_images(entry_id:str,version:str,run_scope:str,query:str='查看资料图片',cursor:str|None=None,mode:str='images')->dict:
    """读取指定版本的资料图片，或通过 mode=next_step 读取已确认步骤的下一步。"""
    return await invoke('get_document_images',locals(),run_scope)

@mcp.tool()
async def get_source_file(entry_id:str,version:str,run_scope:str,query:str='查看原文件')->dict:
    """获取指定已发布资料的原文件引用，不执行平台文件发送。"""
    return await invoke('get_source_file',locals(),run_scope)

@mcp.tool()
async def search_my_history(query:str,run_scope:str,limit:int=10)->dict:
    """查询当前已认证用户最近90天内的个人聊天历史。"""
    return await invoke('search_my_history',{'query':query,'limit':limit},run_scope)

@asynccontextmanager
async def lifespan(app):
    async def maintenance():
        while True:
            await asyncio.to_thread(store.cleanup)
            await asyncio.sleep(86400)
    task=asyncio.create_task(maintenance())
    async with mcp.session_manager.run():
        try: yield
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

async def health(request): return JSONResponse({'status':'ok','service':'workrag-mcp','tools':4})
inner=Starlette(routes=[Route('/health',health),Mount('/',app=mcp.streamable_http_app())],lifespan=lifespan)

class Auth:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']=='http' and scope['path']!='/health':
            headers=dict(scope['headers']); supplied=headers.get(b'authorization',b'')
            expected=('Bearer '+os.environ['WORKRAG_MCP_ACCESS_TOKEN']).encode()
            if not hmac.compare_digest(supplied,expected):
                return await JSONResponse({'error':'authentication_required'},status_code=401)(scope,receive,send)
        await self.app(scope,receive,send)
app=Auth(inner)
