'use strict';

// The child opens the browser itself. URLs, OAuth codes and token contents never
// enter this module; only a bounded fixed-word status protocol is accepted.
function createCodexLogin({spawn,binary,home,enabled=false,onChange=()=>{},closeTimeoutMs=5000}){
  let current='idle',child=null,buffer='',timer=null;
  const allowed=new Set(['waiting','completed','cancelled','unavailable','error']);
  function update(value){if(current!==value){current=value;onChange(value);}}
  function cancel(){if(child){try{child.stdin.write('cancel\n');}catch{};}return {status:current};}
  function stopSoon(){cancel();}
  function start(){
    if(!enabled)return {status:'unavailable'};
    if(child)return {status:current};
    const env={...process.env};
    for(const key of ['OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','OPENAI_BASE_URL','OPENAI_API_BASE'])delete env[key];
    let next;
    try{next=spawn(binary,['--home',home,'codex-app-login'],{env,shell:false,windowsHide:true,stdio:['pipe','pipe','ignore']});}
    catch{update('error');return {status:current};}
    child=next;buffer='';update('starting');
    timer=setTimeout(()=>{update('error');stopSoon(next);},610000);timer.unref?.();
    next.stdin.on('error',()=>{});
    next.stdout.on('data',chunk=>{
      if(current==='error')return;
      buffer+=chunk.toString('utf8');
      if(Buffer.byteLength(buffer,'utf8')>8192){buffer='';update('error');stopSoon(next);return;}
      let pos;
      while((pos=buffer.indexOf('\n'))>=0){
        const line=buffer.slice(0,pos);buffer=buffer.slice(pos+1);let msg;
        try{msg=JSON.parse(line);}catch{update('error');stopSoon(next);return;}
        if(!msg||typeof msg!=='object'||Array.isArray(msg)||Object.keys(msg).length!==1||!allowed.has(msg.status)){
          update('error');stopSoon(next);return;
        }
        update(msg.status);
      }
    });
    next.once('error',()=>{update('error');});
    next.once('close',()=>{
      if(timer)clearTimeout(timer);timer=null;
      if(child===next)child=null;
      if(!['completed','cancelled','unavailable','error'].includes(current))update('error');
    });
    return {status:current};
  }
  function close(){
    if(!child)return Promise.resolve();
    const target=child;return new Promise((resolve,reject)=>{
      let done=false,timer;
      const finish=()=>{if(!done){done=true;clearTimeout(timer);resolve();}};
      target.once('close',finish);
      timer=setTimeout(()=>{if(!done){done=true;target.removeListener('close',finish);update('error');reject(new Error('login-stop-unconfirmed'));}},closeTimeoutMs);
      cancel();
    });
  }
  return Object.freeze({start,cancel,close,view:()=>({enabled,status:current})});
}
module.exports={createCodexLogin};
