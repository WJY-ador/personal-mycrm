const {test}=require('node:test');const assert=require('node:assert/strict');
const {OutputTail,failureLine,hasLiveProcess,OUTPUT_LIMIT,LINE_LIMIT}=require('../src/sidecar.cjs');
test('failure shows the last non-empty sidecar line',()=>{
 assert.equal(failureLine(1,'시작\n서버에 닿지 못했어요. 주소·네트워크를 확인하세요.\n\n  \r\n'),'서버에 닿지 못했어요. 주소·네트워크를 확인하세요.');
 assert.equal(failureLine(3,'a\r\nb\r\n'),'b');assert.equal(failureLine(null,'killed\n'),'killed');
});
test('success, empty or whitespace-only output yields no detail',()=>{
 assert.equal(failureLine(0,'오류처럼 보이는 줄\n'),null);assert.equal(failureLine(1,''),null);assert.equal(failureLine(1,' \n\t\n'),null);assert.equal(failureLine(1,undefined),null);
});
test('detail is capped at 300 characters without splitting Korean',()=>{
 const line=failureLine(1,'가'.repeat(1000));assert.equal(Array.from(line).length,LINE_LIMIT);assert.equal(line,'가'.repeat(LINE_LIMIT));
});
test('output tail keeps only the last 8KB and decodes multi-byte text split across chunks',()=>{
 const t=new OutputTail();const bytes=Buffer.from('서버에 닿지 못했어요\n');
 for(let i=0;i<5000;i++)t.push(Buffer.from('x'.repeat(10)+'\n'));
 t.push(bytes.subarray(0,4));t.push(bytes.subarray(4));
 assert(Buffer.byteLength(t.text())<=OUTPUT_LIMIT+3);assert.equal(failureLine(1,t.text()),'서버에 닿지 못했어요');
 assert(t.size<=OUTPUT_LIMIT*2);
});
test('tray stop is offered only while a sidecar process is live',()=>{
 assert.equal(hasLiveProcess({}),false);assert.equal(hasLiveProcess(undefined),false);
 assert.equal(hasLiveProcess({viewer:{state:'stopped'},jobs:{state:'failed'}}),false);
 assert.equal(hasLiveProcess({viewer:{state:'authentication-required'}}),false);
 for(const state of ['starting','running','retry-wait'])assert.equal(hasLiveProcess({viewer:{state:'stopped'},jobs:{state}}),true,state);
});
