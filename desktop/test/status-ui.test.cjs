'use strict';
// Process names in the connection window's status line.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/renderer.js'),'utf8');
function render(processes){
 const nodes=new Map();
 const element=id=>{if(!nodes.has(id))nodes.set(id,{id,textContent:'',value:'',hidden:false,disabled:false,checked:false});return nodes.get(id);};
 let show;
 const status={version:'0.1.2',pc:{session:'ok',registered:true},connection:{connected:true},processes,ready:true,busy:false,codexCandidates:[]};
 const mycrm={status:async()=>({ok:true,value:status}),onStatus:fn=>{show=fn;},updateState:async()=>({ok:false}),onUpdate:()=>{}};
 vm.runInNewContext(source,{window:{mycrm,addEventListener:()=>{}},document:{getElementById:element,querySelectorAll:()=>[],activeElement:null},
  console,setInterval:()=>1,clearInterval:()=>{}});
 show(status);return element('process-detail').textContent;
}
test('each process has its own name: viewer, jobs and chat',()=>{
 assert.equal(render({viewer:{state:'running'},jobs:{state:'running'},chat:{state:'running'}}),'원문 뷰어: 실행 중, 대화 정리: 실행 중, AI 대화: 실행 중');
});
test('viewer and jobs without chat (chat held by the consent lock)',()=>{
 assert.equal(render({viewer:{state:'running'},jobs:{state:'starting'}}),'원문 뷰어: 실행 중, 대화 정리: 시작 중');
});
test('an unknown process shows its own name, not the viewer',()=>{
 assert.equal(render({viewer:{state:'running'},other:{state:'failed'}}),'원문 뷰어: 실행 중, other: 실행 실패');
});
