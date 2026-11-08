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

test('private local bridge authenticates supervised child and forwards only a validated request',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-bridge-'));
 await fs.chmod(root,0o700);
 const calls=[];
 const bridge=new ConsentBridge({directory:root,uid:process.getuid?.(),handler:async request=>{calls.push(request);return true;}});
 try{
  const env=await bridge.start();
  const stat=await fs.stat(env.MYCRM_CHAT_BRIDGE_SOCKET);
  assert.equal(stat.mode&0o777,0o600);
  assert.match(env.MYCRM_CHAT_BRIDGE_TOKEN,/^[A-Za-z0-9_-]{43}$/);
  const request={version:1,token:env.MYCRM_CHAT_BRIDGE_TOKEN,request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'};
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,request),{ok:true});
  assert.deepEqual(calls,[{request_id:'session_request_1',device_bearer:'Bearer synthetic-device-token'}]);
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,{...request,token:'wrong'}),{ok:false});
  assert.equal(calls.length,1);
  assert.deepEqual(await send(env.MYCRM_CHAT_BRIDGE_SOCKET,{...request,request_id:'bad id'}),{ok:false});
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

test('desktop Stop aborts native approval immediately before the supervised child exits',async()=>{
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

test('closing the supervised child socket aborts the native approval handler',async()=>{
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
