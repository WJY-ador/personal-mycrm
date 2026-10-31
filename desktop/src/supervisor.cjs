'use strict';
const cp = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
class Supervisor {
  constructor({binary,home,spawn=cp.spawn,log=()=>{},changed=()=>{},restartDelay=30000,stopGrace=50000}) {
    Object.assign(this,{binary,home,spawn,log,changed,restartDelay,stopGrace}); this.entries=new Map(); this.closing=false;
  }
  snapshot() { return Object.fromEntries([...this.entries].map(([k,v])=>[k,{state:v.state,restarts:v.restarts,code:v.code ?? null}])); }
  start(name,args,{allowCli=false}={}) {
    if(this.closing) throw new Error('closing');
    const old=this.entries.get(name);
    if(old?.child || old?.timer || old?.state==='stopping') return;
    const entry={args,allowCli,state:'starting',intent:true,restarts:0,child:null,timer:null};
    this.entries.set(name,entry); this._launch(name,entry);
  }
  _launch(name,e) {
    if(!e.intent || this.closing) return;
    const env={...process.env,MYCRM_DESKTOP_CONTROL:'1',PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1'};
    delete env.MYCRM_JOBS_ALLOW_REAL_CLI;
    if(e.allowCli) env.MYCRM_JOBS_ALLOW_REAL_CLI='1';
    let child;
    try { child=this.spawn(this.binary,['--home',this.home,...e.args],{env,shell:false,windowsHide:true,stdio:['pipe','pipe','pipe']}); }
    catch { e.state='failed';e.intent=false;this.log(name,'spawn-error');this.changed();return; }
    e.child=child;e.state='running';this.log(name,'started');this.changed();
    // Child output can contain source material. Consume it without persisting it.
    child.stdout?.on('data',()=>{});child.stderr?.on('data',()=>{});child.stdin?.on('error',()=>{});
    child.once('error',()=> {e.state='failed';e.intent=false;this.log(name,'spawn-error');this.changed();});
    child.once('close',(code,signal)=> {
      if(e.child !== child) return;
      e.child=null;e.code=code;e.state='stopped';this.log(name,'exit',code);
      if(e.intent && !this.closing && signal && e.restarts<3) {
        e.restarts++;e.state='retry-wait';
        e.timer=setTimeout(()=> {e.timer=null;this._launch(name,e);},this.restartDelay*e.restarts);
      } else {e.intent=false; if(code && code!==0) e.state=code===3?'authentication-required':'failed';}
      this.changed();
    });
  }
  async stop(name) {
    const e=this.entries.get(name);if(!e)return;
    e.intent=false;if(e.timer){clearTimeout(e.timer);e.timer=null;}
    const child=e.child;if(!child){e.state='stopped';this.changed();return;}
    e.state='stopping';this.changed();
    await new Promise(resolve=> {
      let done=false;
      const finish=()=>{if(done)return;done=true;clearTimeout(timer);resolve();};
      const timer=setTimeout(()=> {
        this.log(name,'forced-stop');
        if(process.platform==='win32' && child.pid) {
          const killer=cp.spawn('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{shell:false,windowsHide:true,stdio:'ignore'});
          killer.once('error',()=>{});
        } else {child.kill('SIGKILL');}
        finish();
      },this.stopGrace);
      child.once('close',finish);
      try {child.stdin?.end('{"command":"stop"}\n');} catch {child.kill('SIGTERM');}
    });
    e.state='stopped';this.changed();
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
