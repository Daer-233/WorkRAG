import http from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { WebSocketServer } from 'ws';
import { Agent } from '@earendil-works/pi-agent-core';
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai';

const token=process.env.PI_HARNESS_TOKEN;
if (!token || token.length<32) throw new Error('PI_HARNESS_TOKEN is required');
const server=http.createServer((req,res)=>{
  if(req.url==='/health') {res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({status:'ok',engine:'pi-agent-core',version:'1.5.0',active}));}
  else {res.writeHead(404);res.end();}
});
let active=0;
const wss=new WebSocketServer({noServer:true,maxPayload:4*1024*1024});
server.on('upgrade',(req,socket,head)=>{
  const received=Buffer.from((req.headers.authorization||'').replace(/^Bearer /,''));const expected=Buffer.from(token);
  if(req.url!=='/run'||received.length!==expected.length||!timingSafeEqual(received,expected)||active>=2){socket.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
  wss.handleUpgrade(req,socket,head,ws=>wss.emit('connection',ws));
});
wss.on('connection',ws=>{
  active++;let agent,started=false,seq=0,calls=0,rounds=0,limited=false;
  const pending=new Map();
  const send=v=>{if(ws.readyState===1)ws.send(JSON.stringify(v));};
  const deadline=setTimeout(()=>{agent?.abort();ws.close(1000,'deadline');},190000);
  const rpc=(op,data)=>new Promise((resolve,reject)=>{const id=String(++seq);pending.set(id,{resolve,reject});send({op,id,...data});});
  ws.on('close',()=>{active--;clearTimeout(deadline);agent?.abort();for(const p of pending.values())p.reject(new Error('request closed'));pending.clear();});
  ws.on('message',async raw=>{
    try {
      const input=JSON.parse(raw.toString());
      if(input.op==='reply') {const p=pending.get(input.id);if(!p)return;pending.delete(input.id);input.error?p.reject(new Error(input.error)):p.resolve(input.value);return;}
      if(input.op!=='start'||started)throw new Error('Invalid run start');started=true;
      if(!Array.isArray(input.tools)||input.tools.length>4)throw new Error('Invalid tool grants');
      const maxCalls=Math.min(12,Math.max(1,input.maxCalls||6));
      const model={id:'langbot-selected',name:'LangBot scoped model',provider:'langbot',api:'openai-completions',baseUrl:'',reasoning:false,input:['text'],contextWindow:32000,maxTokens:8192,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
      const usage={input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
      const streamFn=(_model,context)=>{
        const stream=createAssistantMessageEventStream();
        void(async()=>{
          try {
            if(++rounds>maxCalls+2)throw new Error('Model round limit');
            const value=await rpc('model',{messages:context.messages});
            const content=[];if(value.content)content.push({type:'text',text:value.content});
            for(const c of value.tool_calls||[])content.push({type:'toolCall',id:c.id,name:c.name,arguments:c.arguments});
            const message={role:'assistant',content,api:model.api,provider:model.provider,model:model.id,usage,timestamp:Date.now(),stopReason:value.tool_calls?.length?'toolUse':'stop',_langbot_provider_fields:value.provider_specific_fields||{}};
            stream.push({type:'done',reason:message.stopReason,message});stream.end();
          } catch(error) {
            stream.push({type:'error',reason:'error',error:{role:'assistant',content:[],api:model.api,provider:model.provider,model:model.id,usage,timestamp:Date.now(),stopReason:'error',errorMessage:'Scoped model bridge failed'}});stream.end();
          }
        })();return stream;
      };
      const tools=input.tools.map(spec=>({...spec,label:spec.name,executionMode:'sequential',execute:async(id,args)=>{
        const value=await rpc('tool',{name:spec.name,args});
        return {content:[{type:'text',text:JSON.stringify(value)}],details:{}};
      }}));
      agent=new Agent({initialState:{model,messages:input.messages,tools},streamFn,toolExecution:'sequential',
        beforeToolCall:()=>{if(calls>=maxCalls){limited=true;return {block:true,reason:'Tool call limit reached',terminate:true};}calls++;},
        finishTurn:()=>limited?{action:'end'}:undefined});
      await agent.continue();
      send({op:'done',messages:agent.state.messages,limited,calls,rounds,error:Boolean(agent.state.errorMessage)});
    } catch(error) {send({op:'failed',error:'Pi run failed'});}
  });
});
server.listen(Number(process.env.PI_HARNESS_PORT||8062),'127.0.0.1',()=>console.log('Pi harness ready on loopback'));
