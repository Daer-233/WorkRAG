import assert from 'node:assert/strict';
import test from 'node:test';
import { Agent } from '@earendil-works/pi-agent-core';
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai';
import { obj, str } from '@earendil-works/pi-schema';

const model = { id:'langbot-selected', name:'LangBot model bridge', api:'openai-completions', provider:'langbot',
  baseUrl:'', reasoning:false, input:['text'], contextWindow:32000, maxTokens:4096,
  cost:{input:0,output:0,cacheRead:0,cacheWrite:0} };
const usage = { input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0} };

// Explicit test provider. No API key, HTTP provider or employee data is used.
function response(content, stopReason='stop') {
  const stream=createAssistantMessageEventStream();
  queueMicrotask(async()=>{
    const base={role:'assistant',api:model.api,provider:model.provider,model:model.id,usage,timestamp:Date.now(),stopReason};
    stream.push({type:'start',partial:{...base,content:[]}});
    if (typeof content==='string') {
      let text='';
      for (const delta of content.split('|')) {
        text+=delta;
        stream.push({type:'text_delta',contentIndex:0,delta,partial:{...base,content:[{type:'text',text}]}});
        await new Promise(r=>setTimeout(r,5));
      }
      content=[{type:'text',text}];
    }
    stream.push({type:'done',reason:stopReason,message:{...base,content}});stream.end();
  });
  return stream;
}

test('Pi emits actual incremental events through a custom model bridge',async()=>{
  const agent=new Agent({initialState:{model},streamFn:()=>response('第一段|第二段')});
  const deltas=[];
  agent.subscribe(event=>{if(event.type==='message_update') deltas.push(event.assistantMessageEvent.delta);});
  await agent.prompt('test');assert.deepEqual(deltas,['第一段','第二段']);
  assert.equal(agent.state.isStreaming,false);
});

test('Pi executes a scoped tool and feeds its result into the next model round',async()=>{
  const identity=Object.freeze({sender:'test-alice'});let rounds=0,called=0;
  const agent=new Agent({initialState:{model,tools:[{name:'search_knowledge',label:'Knowledge',description:'Scoped test tool',
    parameters:obj({query:str()}),execute:async(id,args)=>{
      assert.equal(identity.sender,'test-alice');assert.equal(args.query,'demo');called++;
      return {content:[{type:'text',text:'evidence-test'}],details:{}};
    }}]},streamFn:(_model,context)=>{
    if(rounds++===0)return response([{type:'toolCall',id:'test-call',name:'search_knowledge',arguments:{query:'demo'}}],'toolUse');
    assert.ok(context.messages.some(m=>m.role==='toolResult'));return response('据本轮证据回答');
  },toolExecution:'sequential'});
  await agent.prompt('knowledge');assert.equal(called,1);assert.equal(rounds,2);
});

test('Independent request Agents keep interleaved user histories isolated',async()=>{
  const make=(name)=>new Agent({initialState:{model},streamFn:()=>response(name)});
  const alice=make('alice'),bob=make('bob');await Promise.all([alice.prompt('question-alice'),bob.prompt('question-bob')]);
  const a=JSON.stringify(alice.state.messages),b=JSON.stringify(bob.state.messages);
  assert.ok(!a.includes('question-bob'));assert.ok(!b.includes('question-alice'));
});
