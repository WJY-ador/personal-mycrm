'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
function app(diagnostic){
 const elements=new Map();const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'',value:'',hidden:false,disabled:false,click(){return this.onclick?.();}});return elements.get(id);};
 const document={getElementById:element,querySelectorAll:()=>[],activeElement:null};
 const mycrm={status:async()=>({ok:false}),onStatus:()=>{},update:async()=>({ok:false}),codexVersion:async()=>({ok:true,value:diagnostic})};
 const context={document,window:{mycrm,addEventListener:()=>{}},console,setInterval:()=>1,clearInterval:()=>{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/renderer.js'),'utf8'),context);
 return {element,context};
}
test('unverified newer CLI explains MyCRM update and a recheck without declaring the chat ready',async()=>{
 const {element}=app({status:'unverified_newer',installed_version:'0.167.0',supported_versions:['0.166.0']});await element('codex-version-check').onclick();
 const text=element('codex-version-state').textContent;assert.match(text,/0\.167\.0/);assert.match(text,/0\.166\.0/);assert.match(text,/MyCRM 업데이트/);assert.match(text,/다시 확인/);assert.doesNotMatch(text,/사용 가능/);
});
test('old managed CLI asks to recheck the managed version without global install instructions',async()=>{
 const {element}=app({status:'too_old',installed_version:'0.165.0',supported_versions:['0.167.0','0.166.0']});await element('codex-version-check').onclick();
 assert.match(element('codex-version-state').textContent,/MyCRM/);
 assert.match(element('codex-version-state').textContent,/다시 확인/);
 assert.doesNotMatch(element('codex-version-state').textContent,/npm install -g|실행 파일을 다시 선택/);
});
test('validated CLI version does not claim that the feature is enabled',async()=>{
 const {element}=app({status:'supported',installed_version:'0.166.0',supported_versions:['0.166.0']});await element('codex-version-check').onclick();
 assert.match(element('codex-version-state').textContent,/활성화 상태는 별도로/);
});
test('configured CLI is checked automatically when settings first become available',async()=>{
 const {element,context}=app({status:'supported',installed_version:'0.166.0',supported_versions:['0.166.0']});
 context.state({version:'0.1.1',ready:true,busy:false,connection:{codexCliConfigured:true,codexModels:[]},processes:{}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.match(element('codex-version-state').textContent,/0\.166\.0/);
});
