'use strict';

// One-request Unix-domain IPC from the supervised chat agent to Electron main.
// The socket lives in a private OS-user directory (0700), is itself 0600, and
// the random capability is inherited only by the supervised child. No renderer
// endpoint exists. Windows deliberately fails closed until a named-pipe ACL
// implementation has equivalent ownership checks.
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const net=require('node:net');
const path=require('node:path');

const MAX_LINE=8192;
const REQUEST_ID=/^[A-Za-z0-9_-]{1,64}$/;
const TOKEN=/^[A-Za-z0-9_-]{43}$/;
const BEARER=/^Bearer [A-Za-z0-9._~+/-]{16,500}$/;
// Request: approval {version:1,token,request_id,device_bearer}.
// Reply contract: {"ok":true} or {"ok":false,"reason":"declined"|"locked"|"failed"}.
// Anything the handler returns other than ok===true becomes a refusal; an unknown reason becomes "failed".
const REASONS=new Set(['declined','locked','failed']);
function reply(result){
 if(result&&typeof result==='object'&&result.ok===true)return {ok:true};
 const reason=result&&typeof result==='object'&&typeof result.reason==='string'&&REASONS.has(result.reason)?result.reason:'failed';
 return {ok:false,reason};
}

function validDirectory(directory,uid){
 return fs.lstat(directory).then(st=>st.isDirectory()&&!st.isSymbolicLink()
  &&(uid===undefined||st.uid===uid)&&(st.mode&0o077)===0).catch(()=>false);
}

class ConsentBridge{
 constructor({directory,uid=process.getuid?.(),handler,platform=process.platform}={}){
  if(typeof directory!=='string'||!path.isAbsolute(directory)||typeof handler!=='function')throw new TypeError('bridge options');
  Object.assign(this,{directory,uid,handler,platform});
  this.server=null;this.socketPath=null;this.token=null;
  this.clients=new Set();
  this.aborters=new Set();
 }
 async start(){
  if(this.platform==='win32')throw new Error('OS IPC unavailable');
  if(this.server)return this.childEnv();
  await fs.mkdir(this.directory,{recursive:true,mode:0o700});
  if(!await validDirectory(this.directory,this.uid))throw new Error('private IPC directory required');
  // Keep the filename short for macOS AF_UNIX path limits. The 64-bit suffix
  // is not the authenticator; the per-run 256-bit capability is.
  this.socketPath=path.join(this.directory,'c'+crypto.randomBytes(8).toString('hex'));
  this.token=crypto.randomBytes(32).toString('base64url');
  // allowHalfOpen: the agent sends its one line and then shuts down its write side (SHUT_WR) while it waits for the
  // reply. Without it Node ends the socket on that FIN, 'close' fires and the handler is aborted before it answers
  // (J-F2). A half-close therefore no longer aborts; the supervised chat child's exit does (main: abortPending).
  this.server=net.createServer({allowHalfOpen:true},socket=>this._handle(socket));
  await new Promise((resolve,reject)=>{
   const onError=e=>{this.server?.removeListener('listening',onListen);reject(e);};
   const onListen=()=>{this.server?.removeListener('error',onError);resolve();};
   this.server.once('error',onError);this.server.once('listening',onListen);
   this.server.listen(this.socketPath);
  });
  await fs.chmod(this.socketPath,0o600);
  return this.childEnv();
 }
 childEnv(){
  if(!this.server||!this.socketPath||!this.token)throw new Error('bridge unavailable');
  return Object.freeze({MYCRM_CHAT_BRIDGE_SOCKET:this.socketPath,MYCRM_CHAT_BRIDGE_TOKEN:this.token});
 }
 _handle(socket){
  this.clients.add(socket);
  const aborter=new AbortController();
  this.aborters.add(aborter);
  socket.on('close',()=>{aborter.abort();this.aborters.delete(aborter);this.clients.delete(socket);});
  socket.setTimeout(5000,()=>socket.destroy());
  let raw=Buffer.alloc(0),settled=false,dispatched=false;
  const finish=async(result)=>{
   if(settled)return;settled=true;
   try{socket.end(JSON.stringify(reply(result))+'\n');}catch{socket.destroy();}
  };
  socket.on('data',chunk=>{
   if(settled)return;
   raw=Buffer.concat([raw,chunk]);
   if(raw.length>MAX_LINE){void finish(null);return;}
   const newline=raw.indexOf(10);
   if(newline<0)return;
   if(newline!==raw.length-1){void finish(null);return;}
   let request;
   try{request=JSON.parse(raw.subarray(0,newline).toString('utf8'));}catch{void finish(null);return;}
   if(!request||typeof request!=='object'||Array.isArray(request)
      ||Object.keys(request).sort().join(',')!=='device_bearer,request_id,token,version'
      ||request.version!==1||typeof request.token!=='string'||!TOKEN.test(request.token)
      ||!crypto.timingSafeEqual(Buffer.from(request.token),Buffer.from(this.token||''))
      ||typeof request.request_id!=='string'||!REQUEST_ID.test(request.request_id)
      ||typeof request.device_bearer!=='string'||!BEARER.test(request.device_bearer)){
    void finish(null);return;
   }
   // A native prompt can remain open until the server challenge expires. Keep the
   // IPC channel alive for that interval; child exit still aborts the handler.
   socket.setTimeout(360000,()=>socket.destroy());
   dispatched=true;
   Promise.resolve().then(()=>this.handler(Object.freeze({request_id:request.request_id,device_bearer:request.device_bearer}),aborter.signal))
    .then(result=>finish(result),()=>finish(null));
  });
  // The client's write side ended. Before a complete request line that is a malformed request; after it, the
  // normal half-close of request_approval: the reply is still written.
  socket.on('end',()=>{if(!dispatched)void finish(null);});
  socket.on('error',()=>{settled=true;});
 }
 abortPending(){for(const aborter of this.aborters)aborter.abort();}
 async close(){
  const server=this.server,socketPath=this.socketPath;
  this.server=null;this.socketPath=null;this.token=null;
  this.abortPending();
  for(const socket of this.clients)socket.destroy();
  this.clients.clear();
  if(server)await new Promise(resolve=>server.close(()=>resolve()));
  if(socketPath)try{await fs.unlink(socketPath);}catch{}
 }
}

module.exports=Object.freeze({ConsentBridge,MAX_LINE,reply});
