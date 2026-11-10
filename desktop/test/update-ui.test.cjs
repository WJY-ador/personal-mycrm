'use strict';
// The connection window's update section draws the updater's state (updater.cjs); it never checks GitHub itself.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/renderer.js'),'utf8');
const BUTTONS=['update-badge','download','update-download','update-install'];
const base={inApp:true,phase:'idle',current:'0.1.2',version:null,percent:null,reason:null};
function makeUi(initial=base,{check='ok'}={}) {
 const nodes=new Map();
 function element(id){if(!nodes.has(id))nodes.set(id,{id,textContent:'',value:'',hidden:BUTTONS.includes(id),disabled:false,checked:false});return nodes.get(id);}
 const status={version:'0.1.2',pc:{session:'none'},connection:{connected:false},processes:{},ready:true,busy:false,codexCandidates:[]};
 const calls=[];let push=null,intervals=0;
 const mycrm={status:async()=>({ok:true,value:status}),onStatus:()=>{},
  updateState:async()=>({ok:true,value:initial}),onUpdate:fn=>{push=fn;},
  checkUpdate:async(...args)=>{calls.push(['check',...args]);return {ok:true,value:{checked:check}};},
  downloadUpdate:async(...args)=>{calls.push(['download',...args]);return {ok:true};},
  installUpdate:async(...args)=>{calls.push(['install',...args]);return {ok:true};},
  openReleases:async(...args)=>{calls.push(['releases',...args]);return {ok:true};}};
 const document={getElementById:element,querySelectorAll:()=>[],activeElement:null};
 vm.runInNewContext(source,{window:{mycrm,addEventListener:()=>{}},document,console,
  setInterval:()=>{intervals++;return 1;},clearInterval:()=>{}});
 const shown=()=>BUTTONS.filter(id=>!element(id).hidden);
 return {element,calls,push:s=>push({...base,...s}),shown,text:()=>element('update-state').textContent,intervals:()=>intervals};
}
const flush=()=>new Promise(resolve=>setTimeout(resolve,10));

test('the panel draws the updater state at start and asks GitHub nothing',async()=>{
 const ui=makeUi({...base,phase:'available',version:'0.2.0'});await flush();
 assert.equal(ui.element('version').textContent,'v0.1.2');
 assert.equal(ui.text(),'새 버전이 나왔어요. 지금 v0.1.2, 새 버전 v0.2.0.');
 assert.deepEqual(ui.shown(),['update-badge','update-download']);
 assert.equal(ui.element('update-badge').textContent,'새 버전 v0.2.0');
 assert.equal(ui.element('update-download').textContent,'지금 업데이트');
 assert.equal(ui.intervals(),0,'no periodic check in the window: the updater checks every 6 hours');
 assert.doesNotMatch(source,/https?:|api\.github|releases\/latest/i);
 assert.deepEqual(ui.calls,[]);
});

test('download, progress, downloaded and restart follow the pushed state',async()=>{
 const ui=makeUi({...base,phase:'available',version:'0.2.0'});await flush();
 await ui.element('update-download').onclick();assert.deepEqual(ui.calls,[['download']]);
 ui.push({phase:'downloading',version:'0.2.0',percent:40});
 assert.equal(ui.text(),'새 버전을 받고 있어요. 40%');assert.deepEqual(ui.shown(),['update-badge']);
 ui.push({phase:'downloaded',version:'0.2.0'});
 assert.equal(ui.text(),'새 버전을 받았어요. 다시 시작하면 설치돼요.');assert.deepEqual(ui.shown(),['update-badge','update-install']);
 await ui.element('update-install').onclick();assert.deepEqual(ui.calls.at(-1),['install']);
});

test('an error offers retry (download again) and the download page',async()=>{
 const ui=makeUi();await flush();
 ui.push({phase:'error',version:'0.2.0',reason:'network'});
 assert.equal(ui.text(),'업데이트를 받지 못했어요.');
 assert.deepEqual(ui.shown(),['update-badge','download','update-download']);
 assert.equal(ui.element('update-download').textContent,'다시 시도');
 ui.push({phase:'error',version:'0.2.0',reason:'install'});
 assert.equal(ui.text(),'업데이트를 설치하지 못했어요.');
 await ui.element('update-download').onclick();await ui.element('download').onclick();
 assert.deepEqual(ui.calls,[['download'],['releases']],'the release page opens without a URL from the window');
});

test('a build without in-app install sends the user to the download page',async()=>{
 const ui=makeUi({...base,inApp:false,phase:'available',version:'0.2.0'});await flush();
 assert.equal(ui.text(),'새 버전이 나왔어요. 지금 v0.1.2, 새 버전 v0.2.0. 다운로드 페이지에서 받아, 앱을 종료한 뒤 설치하세요.');
 assert.deepEqual(ui.shown(),['update-badge','download']);
});

test('a manual check reports the latest version, a failure, or keeps a known new version',async()=>{
 const ok=makeUi();await flush();
 assert.equal(ok.text(),'새 버전이 나오면 여기와 대시보드에 알려 드려요.');
 await ok.element('update').onclick();assert.deepEqual(ok.calls,[['check']]);
 assert.equal(ok.text(),'최신 버전을 쓰고 있어요. 지금 v0.1.2.');assert.deepEqual(ok.shown(),[]);
 const bad=makeUi(base,{check:'failed'});await flush();
 await bad.element('update').onclick();
 assert.equal(bad.text(),'업데이트를 확인하지 못했어요. 네트워크를 확인하고 다시 시도해 주세요.');
 assert.equal(bad.element('message').textContent,'');
 bad.push({phase:'available',version:'0.2.0'});
 assert.match(bad.text(),/새 버전 v0\.2\.0\. 최신 상태를 다시 확인하지 못했어요\./);
 ok.push({phase:'checking'});assert.equal(ok.text(),'업데이트를 확인하고 있어요.');
 bad.push({phase:'checking'});bad.push({phase:'idle'});
 assert.equal(bad.text(),'새 버전이 나오면 여기와 대시보드에 알려 드려요.','a later check clears the old failure');
});
