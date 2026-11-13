'use strict';
const cp = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
class Supervisor {
  constructor({binary,home,spawn=cp.spawn,log=()=>{},changed=()=>{},exited=()=>{},restartDelay=30000,stopGrace=50000,killConfirmGrace=5000,authRestartDelay=2000,authWindow=600000,now=Date.now}) {
    Object.assign(this,{binary,home,spawn,log,changed,exited,restartDelay,stopGrace,killConfirmGrace,authRestartDelay,authWindow,now}); this.entries=new Map(); this.closing=false;
  }
  snapshot() { return Object.fromEntries([...this.entries].map(([k,v])=>[k,{state:v.state,restarts:v.restarts,code:v.code ?? null}])); }
  start(name,args,{allowCli=false,env={}}={}) {
    if(this.closing) throw new Error('closing');
    if(!env||typeof env!=='object'||Array.isArray(env)||Object.keys(env).some(k=>!/^[A-Z0-9_]{1,64}$/.test(k)||typeof env[k]!=='string'||/[\r\n\x00]/.test(env[k])))throw new Error('environment');
    const old=this.entries.get(name);
    if(old?.child || old?.timer || old?.state==='stopping') return;
    const entry={args,allowCli,env:{...env},state:'starting',intent:true,restarts:0,child:null,timer:null};
    this.entries.set(name,entry); this._launch(name,entry);
  }
  _launch(name,e) {
    if(!e.intent || this.closing) return;
    const env={...process.env,MYCRM_DESKTOP_CONTROL:'1',PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1'};
    delete env.MYCRM_JOBS_ALLOW_REAL_CLI;
    if(e.allowCli) env.MYCRM_JOBS_ALLOW_REAL_CLI='1';
    Object.assign(env,e.env);
    let child;
    try { child=this.spawn(this.binary,['--home',this.home,...e.args],{env,shell:false,windowsHide:true,stdio:['pipe','pipe','pipe']}); }
    catch { e.state='failed';e.intent=false;this.log(name,'spawn-error');this.changed();return; }
    e.child=child;e.state='running';e.launchedAt=this.now();this.log(name,'started');this.changed();
    // Child output can contain source material. Consume it without persisting it.
    child.stdout?.on('data',()=>{});child.stderr?.on('data',()=>{});child.stdin?.on('error',()=>{});
    child.once('error',()=> {e.state='failed';e.intent=false;this.log(name,'spawn-error');this.changed();});
    child.once('close',(code,signal)=> {
      if(e.child !== child) return;
      e.child=null;e.code=code;e.state='stopped';this.log(name,'exit',code);
      // exited(name): every child exit, before any restart (main aborts the chat consent approvals the child held).
      try{this.exited(name);}catch{}
      if(e.intent && !this.closing && signal && e.restarts<3) {
        e.restarts++;e.state='retry-wait';
        e.timer=setTimeout(()=> {e.timer=null;this._launch(name,e);},this.restartDelay*e.restarts);
      } else if(code===3 && e.intent && !this.closing && (!e.authRetried || this.now()-e.launchedAt>this.authWindow)) {
        // Exit 3 = the token it holds was replaced (rotate) or refused. Start once more so it reads the current token;
        // a second exit 3 soon after stops it (authentication-required), so a revoked token never loops.
        e.authRetried=true;e.state='retry-wait';this.log(name,'auth-restart');
        e.timer=setTimeout(()=> {e.timer=null;this._launch(name,e);},this.authRestartDelay);
      } else {e.intent=false; if(code && code!==0) e.state=code===3?'authentication-required':'failed';}
      this.changed();
    });
  }
  // One small control record to a running child's stdin (chat: {"command":"ai-refresh"}). False when it is not running.
  send(name,record) {
    const child=this.entries.get(name)?.child;
    if(!child?.stdin||child.stdin.destroyed||child.stdin.writableEnded)return false;
    try{child.stdin.write(JSON.stringify(record)+'\n');return true;}catch{return false;}
  }
  async stop(name) {
    const e=this.entries.get(name);if(!e)return;
    e.intent=false;if(e.timer){clearTimeout(e.timer);e.timer=null;}
    const child=e.child;if(!child){e.state='stopped';this.changed();return true;}
    e.state='stopping';this.changed();
    await new Promise((resolve,reject)=> {
      let done=false,graceTimer,confirmTimer;
      const finish=()=>{if(done)return;done=true;clearTimeout(graceTimer);clearTimeout(confirmTimer);resolve(true);};
      const confirmExit=()=> {
        if(done)return;
        this.log(name,'forced-stop');
        // Signal only this ChildProcess object. Never use a PID-based helper or
        // process-group signal, which could target a reused PID or another app.
        if(child.exitCode==null&&child.signalCode==null){try{child.kill('SIGKILL');}catch{}}
        confirmTimer=setTimeout(()=>{
          if(done)return;
          done=true;child.removeListener('close',finish);clearTimeout(graceTimer);
          this.log(name,'stop-unconfirmed');
          const error=new Error('child close confirmation timeout');
          error.code='CHILD-CLOSE-UNCONFIRMED';
          // Keep entry in stopping state and retain child identity. A caller must
          // not treat a signal request or timeout as proof that the child exited.
          this.changed();
          reject(error);
        },this.killConfirmGrace);
      };
      graceTimer=setTimeout(confirmExit,this.stopGrace);
      child.once('close',finish);
      try {child.stdin?.end('{"command":"stop"}\n');}
      catch {if(child.exitCode==null&&child.signalCode==null){try{child.kill('SIGTERM');}catch{}}}
    });
    e.state='stopped';this.changed();return true;
  }
  async stopAll({closing=false}={}) {if(closing)this.closing=true;await Promise.all([...this.entries.keys()].map(k=>this.stop(k)));}
}
function diagnosticLog(directory) {
  fs.mkdirSync(directory,{recursive:true,mode:0o700});
  const file=path.join(directory,'desktop.log');
  return (component,event,code)=> {
    try {
      if(fs.existsSync(file)&&fs.statSync(file).size>256*1024){try{fs.unlinkSync(file+'.1');}catch{}fs.renameSync(file,file+'.1');}
      fs.appendFileSync(file,JSON.stringify({at:new Date().toISOString(),component,event,code:Number.isInteger(code)?code:null})+'\n',{mode:0o600});
    } catch { /* diagnostic failure must not block shutdown or alter data */ }
  };
}
module.exports={Supervisor,diagnosticLog};
