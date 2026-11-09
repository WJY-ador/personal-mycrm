'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/renderer.js'),'utf8');
function makeUi(result) {
 const nodes=new Map();
 function element(id){if(!nodes.has(id))nodes.set(id,{id,textContent:'',value:'',hidden:['update-badge','download'].includes(id),disabled:false,checked:false});return nodes.get(id);}
 const status={version:'0.1.1',pc:{session:'none'},connection:{connected:false},processes:{},ready:true,busy:false,codexCandidates:[]};
 let calls=0;
 const mycrm={status:async()=>({ok:true,value:status}),onStatus:()=>{},update:async()=>{calls++;return typeof result==='function'?result(calls):result},download:async()=>({ok:true})};
 const document={getElementById:element,querySelectorAll:()=>[],activeElement:null};
 let periodic,cleared=false;const events={};
 vm.runInNewContext(source,{window:{mycrm,addEventListener:(name,fn)=>{events[name]=fn;}},document,console,
  setInterval:(fn,delay)=>{periodic={fn,delay};return 42;},clearInterval:id=>{if(id===42)cleared=true;}});
 return {element,calls:()=>calls,periodic:()=>periodic,events,cleared:()=>cleared};
}
const flush=()=>new Promise(resolve=>setTimeout(resolve,20));
test('startup checks for new stable release and displays installed and available versions',async()=>{
 const ui=makeUi({ok:true,value:{state:'available',version:'v0.1.2',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.2'}});
 await flush();assert.equal(ui.calls(),1);assert.equal(ui.element('version').textContent,'v0.1.1');
 assert.match(ui.element('update-state').textContent,/v0\.1\.2/);assert.equal(ui.element('download').hidden,false);
 assert.equal(ui.element('update-badge').hidden,false);assert.match(ui.element('update-badge').textContent,/v0\.1\.2/);
});
test('startup update network failure leaves current version visible and no false success',async()=>{
 const ui=makeUi({ok:false,error:'연결 실패'});await flush();assert.equal(ui.element('version').textContent,'v0.1.1');
 assert.match(ui.element('update-state').textContent,/확인하지 못/);assert.equal(ui.element('download').hidden,true);assert.equal(ui.element('message').textContent,'');
});
test('a current stable release displays its version and no download prompt',async()=>{
 const ui=makeUi({ok:true,value:{state:'current',version:'v0.1.1',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.1'}});
 await flush();assert.match(ui.element('update-state').textContent,/v0\.1\.1/);assert.equal(ui.element('version').textContent,'v0.1.1');assert.equal(ui.element('download').hidden,true);
});
test('when no stable release exists no version is claimed and no download is offered',async()=>{
 const ui=makeUi({ok:true,value:{state:'not-published',url:'https://github.com/WJY-ador/personal-mycrm/releases'}});
 await flush();assert.match(ui.element('update-state').textContent,/게시된 안정 버전이 없습니다/);assert.equal(ui.element('download').hidden,true);
});
test('manual update check still works after automatic check',async()=>{
 const ui=makeUi({ok:true,value:{state:'current',version:'v0.1.1',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.1'}});
 await flush();await ui.element('update').onclick();assert.equal(ui.calls(),2);
});
test('an app left open rechecks releases periodically',async()=>{
 const ui=makeUi({ok:true,value:{state:'current',version:'v0.1.1',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.1'}});
 await flush();assert.equal(ui.periodic().delay,6*60*60*1000);await ui.periodic().fn();assert.equal(ui.calls(),2);
 ui.events.pagehide();assert.equal(ui.cleared(),true);
});
test('manual or timed checks do not duplicate an in-flight request',async()=>{
 let finishStartup;
 const ui=makeUi(call=>call===1?new Promise(resolve=>{finishStartup=resolve;}):{ok:true,value:{state:'current',version:'v0.1.1'}});
 await ui.element('update').onclick();await ui.periodic().fn();assert.equal(ui.calls(),1);
 finishStartup({ok:true,value:{state:'available',version:'v0.1.2',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.2'}});
 await flush();assert.match(ui.element('update-state').textContent,/v0\.1\.2/);assert.equal(ui.element('download').hidden,false);
 await ui.element('update').onclick();assert.equal(ui.calls(),2);
});
test('a failed periodic check preserves an earlier update notice and download link',async()=>{
 const ui=makeUi(call=>call===1?{ok:true,value:{state:'available',version:'v0.1.2',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.2'}}:{ok:false});
 await flush();await ui.periodic().fn();assert.match(ui.element('update-state').textContent,/v0\.1\.2/);
 assert.equal(ui.element('download').hidden,false);assert.equal(ui.element('update-badge').hidden,false);
 assert.equal(ui.element('message').textContent,'');
});
