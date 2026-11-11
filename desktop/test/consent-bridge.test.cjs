'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const net=require('node:net');
const os=require('node:os');
const path=require('node:path');
const {ConsentBridge}=require('../src/consent-bridge.cjs');

async function send(socketPath, body){
 return new Promise((resolve,reject)=>{
  const socket=net.createConnection(socketPath);
  let data='';
  socket.setEncoding('utf8');
  socket.on('connect',()=>socket.end(JSON.stringify(body)+'\n'));
  socket.on('data',chunk=>data+=chunk);
  socket.on('end',()=>{try{resolve(JSON.parse(data));}catch{reject(new Error('bad response'));}});
  socket.on('error',reject);
 });
}

test('private local bridge authenticates supervised child and forwards only a validated request',{skip:process.platform==='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-'));
 await fs.chmod(root,0o700);
 const calls=[];
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:async request=>{calls.push(request);return {ok:true};}});
 try{
  const env=await bridge.start();
  const stat=await fs.stat(env.MYCRM_CHAT_BRIDGE_SOCKET);
  assert.equal(stat.mode&0o777,0o600);
  assert.match(env.MYCRM_CHAT_BRIDGE_TOKEN,/^[A-Za-z0-9_-]{43}$/);
  const request={version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'};
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:true});
  assert.deepEqual(calls,[{request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'}]);
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,{...request,token:'wrong'}),{ok:false,reason:'failed'});
  assert.equal(calls.length,1);
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,{...request,request_id:'bad id'}),{ok:false,reason:'failed'});
  assert.equal(calls.length,1);
 }finally{
  await bridge.close();
  await fs.rm(root,{recursive:true,force:true});
 }
});

test('bridge refuses non-private or non-owned socket directory',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-open-'));
 await fs.chmod(root,0o755);
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:async()=>true});
 try{await assert.rejects(bridge.start());}finally{await bridge.close();await fs.rm(root,{recursive:true,force:true});}
});

test('desktop Stop aborts native approval immediately before the supervised child exits',{skip:process.platform==='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-abort-'));
 await fs.chmod(root,0o700);
 let signal,startedResolve;
 const started=new Promise(resolve=>{startedResolve=resolve;});
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:(_request,s)=>{
  signal=s;startedResolve();return new Promise(()=>{});
 }});
 let client;
 try{
  const env=await bridge.start();
  client=net.createConnection(env.MYCRM_CHAT_BRIDGE_SOCKET);
  await new Promise((resolve,reject)=>{
   client.once('connect',()=>client.write(JSON.stringify({version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,
    request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'})+'\n'));
   client.once('error',reject);
   started.then(resolve,reject);
  });
  assert.equal(signal.aborted,false);
  bridge.abortPending(); // desktop Stop can cancel before the supervised child is terminated
  assert.equal(signal.aborted,true);
  const closed=new Promise(resolve=>client.once('close',resolve));
  client.destroy();
  await closed;
  assert.equal(signal.aborted,true);
 }finally{
  client?.destroy();await bridge.close();await fs.rm(root,{recursive:true,force:true});
 }
});

test('closing the supervised child socket aborts the native approval handler',{skip:process.platform==='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-close-'));
 await fs.chmod(root,0o700);
 let signal,startedResolve;
 const started=new Promise(resolve=>{startedResolve=resolve;});
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:(_request,s)=>{
  signal=s;startedResolve();return new Promise(()=>{});
 }});
 let client;
 try{
  const env=await bridge.start();
  client=net.createConnection(env.MYCRM_CHAT_BRIDGE_SOCKET);
  await new Promise((resolve,reject)=>{
   client.once('connect',()=>client.write(JSON.stringify({version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,
    request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'})+'\n'));
   client.once('error',reject);started.then(resolve,reject);
  });
  assert.equal(signal.aborted,false);
  const closed=new Promise(resolve=>client.once('close',resolve));
  client.destroy();await closed;
  for(let i=0;i<50&&!signal.aborted;i++)await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(signal.aborted,true);
 }finally{client?.destroy();await bridge.close();await fs.rm(root,{recursive:true,force:true});}
});

test('Windows bridge refuses startup before creating a socket or invoking the handler',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-windows-'));
 let called=false;
 const bridge=new ConsentBridge({directory:root,platform:'win32',handler:async()=>{called=true;return true;}});
 try{
  await assert.rejects(bridge.start(),/OS IPC unavailable/);
  assert.equal(called,false);
  assert.equal(bridge.server,null);
  assert.equal(bridge.socketPath,null);
  assert.throws(()=>bridge.childEnv(),/bridge unavailable/);
 }finally{await bridge.close();await fs.rm(root,{recursive:true,force:true});}
});

test('bridge reply is {ok:true} or {ok:false,reason} with reason from the fixed list only',()=>{
 const {reply}=require('../src/consent-bridge.cjs');
 assert.deepEqual(reply({ok:true}),{ok:true});
 assert.deepEqual(reply({ok:true,reason:'declined'}),{ok:true});
 for(const reason of ['declined','locked','failed'])assert.deepEqual(reply({ok:false,reason}),{ok:false,reason});
 for(const result of [true,false,undefined,null,{},{ok:false},{ok:'true'},{ok:false,reason:'DECLINED'},{ok:false,reason:'other'},
   {ok:false,reason:['declined']},'declined'])
  assert.deepEqual(reply(result),{ok:false,reason:'failed'},JSON.stringify(result));
});

test('bridge forwards the handler refusal reason and turns a handler throw into failed',{skip:process.platform==='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-reason-'));
 await fs.chmod(root,0o700);
 const results=[{ok:false,reason:'declined'},{ok:false,reason:'locked'},{ok:false,reason:'surprise'},true];
 let i=0;
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:async()=>{
  const r=results[i++];if(r===undefined)throw new Error('synthetic handler failure');return r;
 }});
 try{
  const env=await bridge.start();
  const request={version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'};
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:false,reason:'declined'});
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:false,reason:'locked'});
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:false,reason:'failed'});
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:false,reason:'failed'});
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:false,reason:'failed'});
 }finally{
  await bridge.close();
  await fs.rm(root,{recursive:true,force:true});
 }
});

test('desktop main passes the runtime result object to the bridge instead of a boolean',()=>{
 const main=require('node:fs').readFileSync(path.join(__dirname,'..','src','main.cjs'),'utf8');
 const line=main.split('\n').find(l=>l.includes('new ConsentBridge('));
 assert.ok(line);
 assert.doesNotMatch(line,/===\s*true/);
 assert.match(line,/consentRuntime\.handle\(input,signal\)/);
});

test('R5: revoke request carries only the device token, needs the capability, and abortPending does not cancel it',{skip:process.platform==='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-revoke-'));
 await fs.chmod(root,0o700);
 const approvals=[],revokes=[];
 let releaseRevoke;
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:async request=>{approvals.push(request);return {ok:true};},
  revokeHandler:async request=>{revokes.push(request);if(releaseRevoke)await new Promise(resolve=>{releaseRevoke=resolve;});return {ok:true};}});
 try{
  const env=await bridge.start();
  const request={version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,kind:'revoke',device_bearer:'Bearer synthetic-device-token'};
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:true});
  assert.deepEqual(revokes,[{device_bearer:'Bearer synthetic-device-token'}]);
  for(const bad of [{...request,token:'wrong'},{...request,kind:'approve'},{...request,version:2},
   {...request,device_bearer:'synthetic-device-token'},{...request,request_id:'session_request_1'}]){
   assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,bad),{ok:false,reason:'failed'});
  }
  assert.equal(revokes.length,1);
  assert.equal(approvals.length,0);
  releaseRevoke=true;
  const pending=send(env.MYCRM_CHAT_BRIDGE_SOCKET,request);
  while(revokes.length<2)await new Promise(resolve=>setImmediate(resolve));
  bridge.abortPending();   // a screen lock aborts approvals at the same moment
  releaseRevoke();
  assert.deepEqual(await pending,{ok:true});
 }finally{
  await bridge.close();
  await fs.rm(root,{recursive:true,force:true});
 }
});

test('R5: a bridge without a revoke handler refuses revoke requests',{skip:process.platform==='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-norevoke-'));
 await fs.chmod(root,0o700);
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:async()=>({ok:true})});
 try{
  const env=await bridge.start();
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,{version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,kind:'revoke',
   device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
 }finally{
  await bridge.close();
  await fs.rm(root,{recursive:true,force:true});
 }
});

test('R5: desktop main wires the revoke handler and starts one revoke at app start without awaiting it',()=>{
 const main=require('node:fs').readFileSync(path.join(__dirname,'..','src','main.cjs'),'utf8');
 assert.match(main,/revokeHandler:async input=>consentRuntime\?await consentRuntime\.revokeWith\(input\)/);
 const starts=main.split('\n').filter(l=>l.includes('revokeAtStart('));
 assert.equal(starts.length,1);
 assert.doesNotMatch(starts[0],/await\s+consentRuntime\.revokeAtStart/);
 assert.match(starts[0],/log\('consent','start-revoke-'\+outcome\)/);
 assert.match(main,/command\(\['chat-consent-revoke'\],null,env\)/);
 const start=main.slice(main.indexOf('async function startChatAgent('));
 const gate=start.indexOf('ensureStartRevoked()'),launch=start.indexOf('startChatSidecar(');
 assert.ok(gate>0&&gate<launch);
 assert.match(start.slice(gate,launch),/throw new Error\('consent-start-revoke-unconfirmed'\)/);
 assert.match(main,/'consent-start-revoke-unconfirmed':'/);
});
