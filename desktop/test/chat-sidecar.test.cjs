'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {startChatSidecar}=require('../src/chat-sidecar.cjs');

test('one supervised chat child receives private consent IPC and runs the normal provider-capable command',async()=>{
 const calls=[];
 const bridge={start:async()=>({MYCRM_CHAT_BRIDGE_SOCKET:'/private/tmp/mycrm-chat.sock',MYCRM_CHAT_BRIDGE_TOKEN:'A'.repeat(43)})};
 const supervisor={start:(...args)=>calls.push(args)};
 const spec=await startChatSidecar(supervisor,bridge);
 assert.deepEqual(spec.args,['chat']);
 assert.deepEqual(calls,[['chat',['chat'],{env:{MYCRM_CHAT_BRIDGE_SOCKET:'/private/tmp/mycrm-chat.sock',MYCRM_CHAT_BRIDGE_TOKEN:'A'.repeat(43)}}]]);
});

test('missing or invalid bridge capability never starts a provider-capable child',async()=>{
 for(const result of [null,{},
  {MYCRM_CHAT_BRIDGE_SOCKET:'/private/tmp/chat.sock'},
  {MYCRM_CHAT_BRIDGE_SOCKET:'/private/tmp/chat.sock',MYCRM_CHAT_BRIDGE_TOKEN:'bad'}]){
  const calls=[];
  await assert.rejects(startChatSidecar({start:(...args)=>calls.push(args)},{start:async()=>result}),/bridge/);
  assert.deepEqual(calls,[]);
 }
});

test('an unsupported OS bridge prevents starting the chat child',async()=>{
 const calls=[];
 await assert.rejects(startChatSidecar({start:(...args)=>calls.push(args)},{start:async()=>{throw new Error('OS IPC unavailable');}}),/OS IPC unavailable/);
 assert.deepEqual(calls,[]);
});

test('desktop main starts only the shared provider-capable chat sidecar',()=>{
 const main=fs.readFileSync(path.join(__dirname,'..','src','main.cjs'),'utf8');
 assert.match(main,/await startChatSidecar\(supervisor,consentBridge\)/);
 assert.doesNotMatch(main,/--consent-only/);
});
