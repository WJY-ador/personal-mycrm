'use strict';
// J-F1: the connection window's first screen (three steps) and the mycrm://connection?step=<step> deep link.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const handoff=require('../src/handoff.cjs');
const source=fs.readFileSync(path.join(__dirname,'../src/renderer.js'),'utf8');

function window_(){
 const nodes=new Map();
 const element=id=>{if(!nodes.has(id))nodes.set(id,{id,textContent:'',value:'',hidden:false,disabled:false,checked:false,className:'',open:false,
  scrolled:0,scrollIntoView(){this.scrolled++;}});return nodes.get(id);};
 element('step-connect').className='step';element('step-provider').className='step';
 let show,step;
 const mycrm={status:async()=>({ok:false}),onStatus:fn=>{show=fn;},updateState:async()=>({ok:false}),onUpdate:()=>{},onSetupStep:fn=>{step=fn;}};
 vm.runInNewContext(source,{window:{mycrm,addEventListener:()=>{}},document:{getElementById:element,querySelectorAll:()=>[],activeElement:null},
  console,setInterval:()=>1,clearInterval:()=>{}});
 return {el:element,show:s=>show(s),step:s=>step(s)};
}
function status({connected=false,session='ok',revoked=false,cli=false,codex=false,models=[]}={}){
 return {version:'0.1.3',ready:true,busy:false,pc:{session,registered:true,revoked},codexCandidates:[],processes:{},
  connection:{connected,cliConfigured:cli,codexCliConfigured:codex,codexModels:models}};
}

test('not connected and logged out: the first screen shows step 2 with the login button, advanced settings folded',()=>{
 const w=window_();w.show(status({session:'none'}));
 assert.equal(w.el('setup').hidden,false);
 assert.equal(w.el('advanced').open,false);assert.equal(w.el('advanced').className,'');
 assert.equal(w.el('step-connect').className,'step current');assert.equal(w.el('step-provider').className,'step');
 assert.equal(w.el('setup-login').hidden,false);assert.equal(w.el('setup-connect').hidden,true);
 assert.equal(w.el('setup-badge').textContent,'3단계 중 2단계');
});

test('logged in but not connected: the connect button; a released PC shows neither button and says how to come back',()=>{
 const w=window_();w.show(status());
 assert.equal(w.el('setup-login').hidden,true);assert.equal(w.el('setup-connect').hidden,false);
 const r=window_();r.show(status({revoked:true,connected:true}));
 assert.equal(r.el('setup-connect').hidden,true);assert.equal(r.el('setup-login').hidden,true);
 assert.match(r.el('step-connect-state').textContent,/해제됐어요/);
});

test('connected without a provider: step 3 is current; Codex needs the path and a model name',()=>{
 const w=window_();w.show(status({connected:true,codex:true,models:[]}));
 assert.equal(w.el('step-connect').className,'step done');assert.equal(w.el('step-provider').className,'step current');
 assert.equal(w.el('setup-badge').textContent,'3단계 중 3단계');assert.equal(w.el('setup').hidden,false);
});

test('step 3 carries the optional allowCli switch, kept in step with the saved preference',()=>{
 const w=window_();const s=status({connected:true});s.allowCli=true;w.show(s);
 assert.equal(w.el('setup-allow-cli').checked,true);
 s.allowCli=false;w.show(s);assert.equal(w.el('setup-allow-cli').checked,false,'the switch does not decide step 3');
 assert.equal(w.el('step-provider').className,'step current');
});

test('connected with Claude or Codex: the usual window, advanced settings open and their heading hidden',()=>{
 for(const s of [status({connected:true,cli:true}),status({connected:true,codex:true,models:['gpt-6-astra']})]){
  const w=window_();w.show(s);
  assert.equal(w.el('setup').hidden,true);assert.equal(w.el('advanced').open,true);assert.equal(w.el('advanced').className,'plain');
 }
});

test('a status refresh does not close advanced settings the user opened on the first screen',()=>{
 const w=window_();w.show(status());w.el('advanced').open=true;w.show(status());
 assert.equal(w.el('advanced').open,true);
});

test('the deep link marks and scrolls to its step; after setup it opens the matching advanced place',()=>{
 const w=window_();w.show(status({connected:true}));
 w.step('provider');
 assert.equal(w.el('step-provider').className,'step current focus');assert.equal(w.el('step-provider').scrolled,1);
 w.step('connect');
 assert.equal(w.el('step-provider').className,'step current');assert.match(w.el('step-connect').className,/focus/);
 w.show(status({connected:true}));assert.match(w.el('step-connect').className,/focus/,'a refresh keeps the mark');
 w.step('permits');assert.equal(w.el('advanced').open,true,'permits sit in the folded settings');assert.equal(w.el('permits').scrolled,1);
 const done=window_();done.show(status({connected:true,cli:true}));done.el('advanced').open=false;
 done.step('provider');assert.equal(done.el('advanced').open,true);assert.equal(done.el('codex-models').scrolled,1);
 done.step('permits');assert.equal(done.el('permits').scrolled,1);
});

test('setup links: mycrm://connection?step=<connect|provider|permits> only; login callbacks are not setup links',()=>{
 assert.deepEqual([...handoff.SETUP_STEPS],['connect','provider','permits']);
 assert.equal(handoff.parseSetupLink('mycrm://connection?step=connect'),'connect');
 assert.equal(handoff.parseSetupLink('mycrm://connection/?step=provider'),'provider');
 assert.equal(handoff.parseSetupLink('mycrm://connection?step=permits'),'permits');
 for(const bad of ['mycrm://connection','mycrm://connection?step=other','mycrm://connection?step=connect&x=1',
  'mycrm://connection?step=connect&step=provider','mycrm://connection/x?step=connect','mycrm://connection?step=connect#a',
  'mycrm://u:p@connection?step=connect','mycrm://setup/connect','https://connection/?step=connect',
  'mycrm://auth/callback?code=aaaaaaaaaaaaaaaa&state=bbbbbbbbbbbbbbbb','mycrm://connection?step='+'a'.repeat(2000),null])
  assert.equal(handoff.parseSetupLink(bad),null,String(bad).slice(0,50));
 assert.equal(handoff.parseCallback('mycrm://connection?step=connect'),null,'a setup link is never a login callback');
});

test('main takes setup links before the login callback and never passes them to the dashboard notice',()=>{
 const main=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
 const guard=main.slice(main.indexOf('function guard(event,url){'));
 assert.ok(guard.indexOf('handoff.parseSetupLink(url)')<guard.indexOf('handoff.isLoginNav(url,HOSTED)'),'a click inside the dashboard window opens the connection window');
 assert.match(main,/setWindowOpenHandler\(\(\{url\}\)=>\{const step=handoff\.parseSetupLink\(url\);if\(step\)setupLink\(step\);/);
 const body=main.slice(main.indexOf('function deepLink(raw){'));
 const setupAt=body.indexOf('handoff.parseSetupLink(raw)'),callbackAt=body.indexOf('handoff.parseCallback(raw)');
 assert.ok(setupAt>0&&setupAt<callbackAt);
 assert.match(main,/register\('auto-connect',\(\)=>exclusively\(async\(\)=>\{/);
 const preload=fs.readFileSync(path.join(__dirname,'../src/preload.cjs'),'utf8');
 assert.match(preload,/autoConnect:call\('auto-connect'\)/);assert.match(preload,/ipcRenderer\.on\('setup-step'/);
});
