const {test}=require('node:test');const assert=require('node:assert/strict');
const g=require('../src/grants.cjs');
const HOSTED='https://personal-mycrm.onrender.com/';
const TOKEN='tok_'+'A'.repeat(40);
test('endpoints stay on the hosted origin and escape ids',()=>{
 assert.equal(g.endpoint(HOSTED,'installations'),HOSTED+'desktop/installations');
 assert.equal(g.endpoint(HOSTED,'grants','in_1'),HOSTED+'desktop/grants?installation=in_1');
 assert.equal(g.endpoint(HOSTED,'redeem','gr_1'),HOSTED+'desktop/grants/gr_1/redeem');
 assert.equal(g.endpoint(HOSTED,'redeem','../x'),HOSTED+'desktop/grants/..%2Fx/redeem');
 assert.equal(g.endpoint(HOSTED,'auto'),HOSTED+'desktop/device/auto');assert.equal(g.endpoint(HOSTED,'rotate'),HOSTED+'desktop/device/rotate');
 assert.throws(()=>g.endpoint(HOSTED,'other'));
 assert.equal(g.HEADERS['X-MyCRM-Desktop'],'1');
});
test('error codes: any 401 means sign in, otherwise the {code} of the body, 429 means slow down',()=>{
 assert.equal(g.errorCode(403,{code:'NOT-OWNER',msg:'m',action:'a'}),'NOT-OWNER');
 assert.equal(g.errorCode(409,{code:'DEVICE-REVOKED'}),'DEVICE-REVOKED');assert.equal(g.errorCode(404,{code:'INSTALLATION-UNKNOWN'}),'INSTALLATION-UNKNOWN');
 assert.equal(g.errorCode(404,{code:'NOT-FOUND'}),'NOT-FOUND');assert.equal(g.errorCode(409,{code:'DEVICE-LIMIT'}),'DEVICE-LIMIT');
 assert.equal(g.errorCode(401,{code:'UNAUTHORIZED'}),'NO-SESSION');assert.equal(g.errorCode(401,null),'NO-SESSION');
 assert.equal(g.errorCode(429,{}),'RATE-LIMIT');assert.equal(g.errorCode(500,'boom'),'FAILED');assert.equal(g.errorCode(400,{code:'SOMETHING-ELSE'}),'FAILED');
 assert.equal(g.errorCode(403,{error:'NOT-OWNER'}),'FAILED');
});
test('rate-limit backoff follows Retry-After within one to ten minutes',()=>{
 assert.equal(g.backoffMs(undefined),60000);assert.equal(g.backoffMs('5'),60000);assert.equal(g.backoffMs('120'),120000);
 assert.equal(g.backoffMs('99999'),600000);assert.equal(g.backoffMs('soon'),60000);
});
test('installation state: released PC or released device counts as revoked',()=>{
 assert.deepEqual(g.installationState({revoked:false,device:{device_id:'is_1',active:true}}),{revoked:false,hasDevice:true});
 assert.deepEqual(g.installationState({revoked:true,device:null}),{revoked:true,hasDevice:false});
 assert.deepEqual(g.installationState({revoked:false,device:{active:false}}),{revoked:true,hasDevice:false});
 assert.deepEqual(g.installationState({revoked:false,device:null}),{revoked:false,hasDevice:false});
 assert.equal(g.installationState(null),null);
});
test('installation id is accepted only in the expected shape',()=>{
 assert.equal(g.parseInstallation({installation_id:'in_ABC-123'}),'in_ABC-123');
 for(const b of [null,{},{installation_id:''},{installation_id:'a b'},{installation_id:'x'.repeat(129)},{installation_id:7},'in_1'])assert.equal(g.parseInstallation(b),null);
});
test('grant list accepts an array or {grants}, drops malformed entries, keeps order',()=>{
 const list=[{grant_id:'g1',scope:'device',expires_at:'x'},{grant_id:'g2',scope:'migration'},{grant_id:'g 3',scope:'device'},{grant_id:'g4',scope:'admin'},null];
 assert.deepEqual(g.parseGrants(list),[{id:'g1',scope:'device'},{id:'g2',scope:'migration'}]);
 assert.deepEqual(g.parseGrants({grants:list}),[{id:'g1',scope:'device'},{id:'g2',scope:'migration'}]);
 assert.deepEqual(g.parseGrants({}),[]);assert.deepEqual(g.parseGrants(null),[]);
 assert.equal(g.parseGrants(Array.from({length:30},(_,i)=>({grant_id:'g'+i,scope:'device'}))).length,10);
});
test('issued token: scope must match, token shape is checked, label is clipped',()=>{
 assert.deepEqual(g.parseIssued({scope:'device',token:TOKEN,account_label:'나\n',device_label:'Studio',device_id:'is_1'},'device'),{scope:'device',token:TOKEN,accountLabel:'나',deviceLabel:'Studio'});
 assert.deepEqual(g.parseIssued({token:TOKEN},'device'),{scope:'device',token:TOKEN,accountLabel:'',deviceLabel:''});
 assert.equal(g.parseIssued({scope:'migration',token:TOKEN},'device'),null);
 for(const t of ['short','x'.repeat(1025),TOKEN+'\n',TOKEN+' x',TOKEN+'\x00',42,null])assert.equal(g.parseIssued({scope:'device',token:t},'device'),null,String(t));
 assert.equal(g.parseIssued(null,'device'),null);
 assert.equal(Array.from(g.parseIssued({token:TOKEN,account_label:'가'.repeat(200)},'device').accountLabel).length,80);
});
test('sidecar commands read the token from stdin; the token is never an argument',()=>{
 assert.deepEqual(g.sidecarArgs('device',HOSTED),['connect','--server',HOSTED,'--token-stdin']);
 assert.deepEqual(g.sidecarArgs('migration',HOSTED),['migrate','login','--server',HOSTED,'--token-stdin']);
 assert.throws(()=>g.sidecarArgs('other',HOSTED));
});
test('run-once from the app always skips Bearer rotate (the app rotates with its session)',()=>{
 assert.deepEqual(g.runOnceArgs(),['run-once','--no-rotate']);
 assert.deepEqual(g.runOnceArgs(true),['run-once','--resume','auth','--no-rotate']);
});
test('polling: timer every 30s, focus polls spaced at least 10s, nothing during a rate-limit backoff or while in flight',()=>{
 assert.equal(g.POLL_MS,30000);
 assert.equal(g.shouldPoll({},0+g.MIN_GAP_MS),true);
 assert.equal(g.shouldPoll({lastAt:1000},1000+9999),false);assert.equal(g.shouldPoll({lastAt:1000},1000+10000),true);
 assert.equal(g.shouldPoll({lastAt:0,inFlight:true},99999),false);
 assert.equal(g.shouldPoll({lastAt:0,backoffUntil:70000},69999),false);assert.equal(g.shouldPoll({lastAt:0,backoffUntil:70000},70000),true);
 // Focus spam for a minute stays within the server's 10 per minute.
 let state={lastAt:-Infinity},count=0;
 for(let t=0;t<60000;t+=100)if(g.shouldPoll(state,t)){count++;state={lastAt:t};}
 assert(count<=6,String(count));
});
test('rotate starts 30 days before expiry; unknown or bad dates never rotate',()=>{
 const now=Date.parse('2026-11-02T00:00:00Z'),day=86400000;
 assert.equal(g.needsRotate(new Date(now+31*day).toISOString(),now),false);
 assert.equal(g.needsRotate(new Date(now+30*day).toISOString(),now),true);
 assert.equal(g.needsRotate(new Date(now-day).toISOString(),now),true);
 for(const v of [null,'','not a date',42])assert.equal(g.needsRotate(v,now),false);
});
test('client info names the PC and OS (process.platform) only',()=>{
 assert.deepEqual(g.clientInfo('Studio.local','darwin'),{client_name:'Studio.local',os:'darwin'});
 assert.deepEqual(g.clientInfo('','win32'),{client_name:'MyCRM PC',os:'win32'});
 assert.equal(g.clientInfo('a'.repeat(200),'linux').client_name.length,80);assert.equal(g.clientInfo('x','sunos').os,'linux');
 assert.equal(g.clientInfo('a\nb','darwin').client_name,'a b');
});
test('notices name the account and device, never a token',()=>{
 assert.deepEqual(g.deliveredNotice('device','나','Studio'),{title:'연결됐어요',body:'나, Studio'});
 assert.deepEqual(g.deliveredNotice('device','',''),{title:'연결됐어요',body:'이 PC를 연결했어요'});
 assert.equal(g.deliveredNotice('migration','나','Studio').title,'이관 토큰을 받았어요');
 assert.match(g.failedNotice('device').title,/연결하지 못했어요/);
 assert.deepEqual(g.failedNotice('migration'),{title:'이관 토큰을 저장하지 못했어요',body:'앱을 최신 버전으로 업데이트한 뒤 대화에서 다시 요청해 주세요.'});
});
test('saved record: malformed input reads as not registered',()=>{
 assert.deepEqual(g.parseRecord('{"installationId":"di_1","revoked":true,"forget":true}'),{installationId:'di_1',revoked:true,released:false,forget:true});
 assert.deepEqual(g.parseRecord('nope'),{installationId:null,revoked:false,released:false,forget:false});
 assert.deepEqual(g.parseRecord({installationId:'a b',revoked:'yes'}),{installationId:null,revoked:false,released:false,forget:false});
});
