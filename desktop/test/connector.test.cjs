// PC connection flow against a fake server and a fake sidecar process: the token must reach the sidecar's stdin
// and nowhere else (sidecar stdout, app log, notifications, renderer view, saved record).
const {test}=require('node:test');const assert=require('node:assert/strict');
const http=require('node:http');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const {spawn}=require('node:child_process');
const g=require('../src/grants.cjs');const {Connector,ConnectError}=require('../src/connector.cjs');
const DEVICE_TOKEN='devtok_'+'D'.repeat(40),MIGRATION_TOKEN='migtok_'+'M'.repeat(40),ROTATED='devtok_'+'R'.repeat(40),AUTO='devtok_'+'A'.repeat(40);
const TOKENS=[DEVICE_TOKEN,MIGRATION_TOKEN,ROTATED,AUTO];
// Fake sidecar: stores what arrives on stdin (the "key store"), writes config.json like `connect`, prints a fixed line.
const SIDECAR=`
const fs=require('node:fs'),path=require('node:path');const [home,...args]=process.argv.slice(2);let input='';
process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{
  const cmd=args.join(' ');fs.appendFileSync(path.join(home,'calls.log'),JSON.stringify({cmd,stdin:input})+'\\n');
  if(process.env.FAKE_FAIL==='1'){console.log('자격 증명 저장소에 쓰지 못했어요.');process.exit(1);}
  if(args[0]==='connect'){const t=input.trim();fs.writeFileSync(path.join(home,'config.json'),JSON.stringify({source_instance_id:t.startsWith('devtok_A')?'src_new':'src_1',device_label:'Studio',token_expires_at:t.startsWith('devtok_R')?'2027-12-01T00:00:00Z':(process.env.FAKE_EXPIRES||'2027-06-01T00:00:00Z')}));console.log('연결했어요(서버 확인 완료).');}
  else if(args[0]==='disconnect'){fs.writeFileSync(path.join(home,'config.json'),JSON.stringify({source_instance_id:null}));console.log('로컬 업로드 토큰: 제거함');}
  else console.log('이관 토큰을 저장했어요.');
});`;
function fakeServer(){
  const s={session:'sess-1',owner:'u1',installations:{},grants:[],requests:[],revoked:false,autoNotOwner:false,nextInstall:1};
  s.server=http.createServer((req,res)=>{
    let body='';req.on('data',c=>body+=c);req.on('end',()=>{
      const url=new URL(req.url,'http://x');const j=body?JSON.parse(body):null;
      s.requests.push({method:req.method,path:url.pathname,query:url.search,cookie:req.headers.cookie,desk:req.headers['x-mycrm-desktop'],body:j});
      const send=(status,obj)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(obj));};
      if(req.headers['x-mycrm-desktop']!=='1')return send(403,{error:'FAILED'});
      if(req.headers.cookie!=='crm_session='+s.session)return send(401,{error:'NO-SESSION'});
      if(url.pathname==='/desktop/installations'){const id='in_'+(s.nextInstall++);s.installations[id]=s.owner;return send(200,{installation_id:id});}
      if(url.pathname==='/desktop/grants'){const id=url.searchParams.get('installation');if(!s.installations[id])return send(404,{error:'INSTALLATION-UNKNOWN'});if(s.installations[id]!==s.owner)return send(403,{error:'NOT-OWNER'});
        return send(200,{grants:s.grants.filter(x=>x.state==='waiting'&&x.installation===id).map(x=>({grant_id:x.id,scope:x.scope,expires_at:'2026-11-02T00:10:00Z'}))});}
      const m=/^\/desktop\/grants\/([^/]+)\/redeem$/.exec(url.pathname);
      if(m){const gr=s.grants.find(x=>x.id===m[1]);if(!gr||gr.state!=='waiting')return send(409,{error:'GRANT-USED'});gr.state='delivered';
        return send(200,{scope:gr.scope,token:gr.scope==='device'?DEVICE_TOKEN:MIGRATION_TOKEN,device_id:'src_1',account_label:'나'});}
      if(url.pathname==='/desktop/device/rotate'){if(s.revoked)return send(409,{error:'DEVICE-REVOKED'});if(s.rotateNotOwner)return send(403,{error:'NOT-OWNER'});return send(200,{scope:'device',token:ROTATED,account_label:'나'});}
      if(url.pathname==='/desktop/device/auto'){if(s.revoked)return send(409,{error:'DEVICE-REVOKED'});if(j.stream_id&&s.autoNotOwner)return send(403,{error:'NOT-OWNER'});return send(200,{scope:'device',token:AUTO,account_label:'나'});}
      send(404,{error:'FAILED'});
    });
  });
  return new Promise(r=>s.server.listen(0,'127.0.0.1',()=>{s.base=`http://127.0.0.1:${s.server.address().port}/`;r(s);}));
}
function nodeRequest(s){
  return (method,url,body)=>new Promise(resolve=>{
    const req=http.request(url,{method,headers:{...g.HEADERS,Cookie:'crm_session='+s.cookie}},res=>{let b='';res.on('data',c=>b+=c);res.on('end',()=>{let p=null;try{p=JSON.parse(b);}catch{}resolve({status:res.statusCode,body:p});});});
    req.on('error',()=>resolve({status:0,body:null}));req.end(body==null?undefined:JSON.stringify(body));
  });
}
function harness(s,{fail=false,expires}={}){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-a3-'));const script=path.join(dir,'sidecar.cjs');fs.writeFileSync(script,SIDECAR);
  const h={dir,logs:[],notices:[],stdout:'',busy:false,ready:true,stored:null};s.cookie=s.session;
  const command=(args,input)=>new Promise(resolve=>{
    const child=spawn(process.execPath,[script,dir,...args],{env:{...process.env,FAKE_FAIL:fail?'1':'0',FAKE_EXPIRES:expires||''},stdio:['pipe','pipe','pipe']});
    let out='';child.stdout.on('data',c=>out+=c);child.stderr.on('data',c=>out+=c);
    child.on('close',code=>{h.stdout+=out;resolve({code,detail:code?out.trim():null});});child.stdin.end(input?input+'\n':'');
  });
  const connection=()=>{try{const c=JSON.parse(fs.readFileSync(path.join(dir,'config.json'),'utf8'));return {connected:!!c.source_instance_id,expires:c.token_expires_at||null,streamId:c.source_instance_id||null,deviceLabel:c.device_label||''};}catch{return {connected:false,expires:null,streamId:null,deviceLabel:''};}};
  let clock=Date.parse('2026-11-02T00:00:00Z');
  h.c=new Connector({hosted:s.base,request:nodeRequest(s),
    store:{load:()=>h.stored,save:r=>{h.stored=JSON.stringify(r);}},
    install:(scope,token)=>command(g.sidecarArgs(scope,s.base),token),forgetLocal:()=>command(['disconnect','--local-only']),
    exclusive:async fn=>{if(h.busy)throw new Error('busy');h.busy=true;try{return await fn();}finally{h.busy=false;}},
    canDeliver:()=>h.ready&&!h.busy,connection,notify:n=>h.notices.push(n),log:(...a)=>h.logs.push(a),
    client:{client_name:'Studio',os:'macos'},now:()=>clock});
  h.tick=ms=>{clock+=ms;};h.calls=()=>{try{return fs.readFileSync(path.join(dir,'calls.log'),'utf8').trim().split('\n').map(JSON.parse);}catch{return [];}};
  h.assertNoLeak=()=>{
    const visible=JSON.stringify([h.logs,h.notices,h.c.view(),h.stored])+h.stdout+JSON.stringify(s.requests.map(r=>[r.query,r.body]));
    for(const t of TOKENS)assert(!visible.includes(t),'token leaked');
    for(const f of fs.readdirSync(dir).filter(n=>n!=='calls.log'))for(const t of TOKENS)assert(!fs.readFileSync(path.join(dir,f),'utf8').includes(t),'token in '+f);
  };
  return h;
}
test('poll registers the installation, redeems a device grant, hands the token to sidecar stdin only, and notifies',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);
    assert.equal(await h.c.poll('timer'),'ok');
    const id=JSON.parse(h.stored).installationId;assert.equal(id,'in_1');
    s.grants.push({id:'gr_1',scope:'device',installation:id,state:'waiting'});
    h.tick(g.POLL_MS);assert.equal(await h.c.poll('timer'),'ok');
    const calls=h.calls();assert.equal(calls.length,1);
    assert.deepEqual(calls[0],{cmd:`connect --server ${s.base} --token-stdin`,stdin:DEVICE_TOKEN+'\n'});
    assert.deepEqual(h.notices,[{title:'연결됐어요',body:'나 · Studio'}]);
    assert.equal(s.grants[0].state,'delivered');
    assert(s.requests.every(r=>r.desk==='1'&&r.cookie==='crm_session=sess-1'));
    assert.deepEqual(s.requests.find(r=>r.path==='/desktop/installations').body,{client_name:'Studio',os:'macos'});
    assert.deepEqual(s.requests.find(r=>r.path.endsWith('/redeem')).body,{installation_id:'in_1'});
    assert.deepEqual(h.c.view(),{session:'ok',revoked:false,registered:true});
    h.assertNoLeak();
  }finally{s.server.close();}
});
test('migration grant goes to `migrate login --token-stdin`',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);await h.c.poll();s.grants.push({id:'gr_m',scope:'migration',installation:'in_1',state:'waiting'});h.tick(g.POLL_MS);await h.c.poll();
    assert.deepEqual(h.calls(),[{cmd:`migrate login --server ${s.base} --token-stdin`,stdin:MIGRATION_TOKEN+'\n'}]);
    assert.equal(h.notices[0].title,'이관 토큰을 받았어요');h.assertNoLeak();
  }finally{s.server.close();}
});
test('no redeem while the sidecar cannot take a token: the grant stays waiting',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);await h.c.poll();s.grants.push({id:'gr_1',scope:'device',installation:'in_1',state:'waiting'});
    h.ready=false;h.tick(g.POLL_MS);await h.c.poll();
    h.ready=true;h.busy=true;h.tick(g.POLL_MS);await h.c.poll();h.busy=false;
    assert.equal(s.requests.filter(r=>r.path.endsWith('/redeem')).length,0);assert.equal(s.grants[0].state,'waiting');assert.equal(h.calls().length,0);
  }finally{s.server.close();}
});
test('sidecar failure after redeem notifies failure without the token',async()=>{
  const s=await fakeServer();try{
    const h=harness(s,{fail:true});await h.c.poll();s.grants.push({id:'gr_1',scope:'device',installation:'in_1',state:'waiting'});h.tick(g.POLL_MS);await h.c.poll();
    assert.equal(h.notices[0].title,'이 PC를 연결하지 못했어요');h.assertNoLeak();
  }finally{s.server.close();}
});
test('without a session: no registration, view says sign in, and nothing opens a browser',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);s.cookie='';
    assert.equal(await h.c.poll(),'no-installation');assert.equal(h.c.view().session,'none');assert.equal(h.stored,null);
    // Focus spam is spaced: three focus events within 10 seconds make one request.
    await h.c.poll('focus');h.tick(3000);await h.c.poll('focus');h.tick(3000);await h.c.poll('focus');
    assert.equal(s.requests.length,1);
    // Auto connection without a session asks for the [로그인] button.
    await assert.rejects(h.c.autoConnect(),e=>e instanceof ConnectError&&e.message==='login');
  }finally{s.server.close();}
});
test('account switch on this PC (NOT-OWNER on poll) registers again for the new account and marks the device for recheck',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);await h.c.poll();await h.c.autoConnect();
    s.owner='u2';s.autoNotOwner=true;h.tick(g.POLL_MS);
    assert.equal(await h.c.poll(),'ok');
    const rec=JSON.parse(h.stored);assert.equal(rec.installationId,'in_2');assert.equal(rec.recheck,true);assert.equal(h.c.needsAuto(),true);
    // Next collection: the old account's device token is removed (disconnect --local-only), then a device for this account.
    await h.c.autoConnect();
    const cmds=h.calls().map(c=>c.cmd);assert.deepEqual(cmds.slice(-2),['disconnect --local-only',`connect --server ${s.base} --token-stdin`]);
    assert.equal(h.calls().at(-1).stdin,AUTO+'\n');assert.equal(JSON.parse(h.stored).recheck,false);
    const autos=s.requests.filter(r=>r.path==='/desktop/device/auto');assert.equal(autos.at(-2).body.stream_id,'src_new');assert.equal(autos.at(-1).body.stream_id,undefined);
    h.assertNoLeak();
  }finally{s.server.close();}
});
test('auto connection: only on request, with installation and client name; revoked PC is not reconnected',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);await h.c.poll();
    assert.equal(s.requests.filter(r=>r.path==='/desktop/device/auto').length,0,'login alone creates no device');
    assert.equal(h.c.needsAuto(),true);await h.c.autoConnect();assert.equal(h.c.needsAuto(),false);
    assert.deepEqual(s.requests.find(r=>r.path==='/desktop/device/auto').body,{client_name:'Studio',os:'macos',installation_id:'in_1'});
    s.revoked=true;await assert.rejects(h.c.autoConnect(),e=>e.message==='revoked');
    assert.equal(h.c.view().revoked,true);
    await assert.rejects(h.c.autoConnect(),e=>e.message==='revoked');   // no server call needed any more
    assert.equal(s.requests.filter(r=>r.path==='/desktop/device/auto').length,2);
    // A conversation reconnect (redeem) clears the revoked mark.
    s.grants.push({id:'gr_1',scope:'device',installation:'in_1',state:'waiting'});h.tick(g.POLL_MS);await h.c.poll();
    assert.equal(h.c.view().revoked,false);h.assertNoLeak();
  }finally{s.server.close();}
});
test('session rotate 30 days before expiry, hourly retry, DEVICE-REVOKED shown, NOT-OWNER forgets the local token',async()=>{
  const s=await fakeServer();try{
    const h=harness(s,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.c.autoConnect();
    h.tick(g.POLL_MS);await h.c.poll();
    assert.equal(h.calls().at(-1).stdin,ROTATED+'\n');
    assert.deepEqual(s.requests.find(r=>r.path==='/desktop/device/rotate').body,{stream_id:'src_new',installation_id:'in_1'});
    // Rotated expiry is far away: no more rotate.
    h.tick(2*g.ROTATE_RETRY_MS);await h.c.poll();assert.equal(s.requests.filter(r=>r.path==='/desktop/device/rotate').length,1);
    h.assertNoLeak();
  }finally{s.server.close();}
  const s2=await fakeServer();try{
    const h=harness(s2,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.c.autoConnect();
    s2.revoked=true;h.tick(g.POLL_MS);assert.equal(await h.c.maybeRotate(),'DEVICE-REVOKED');assert.equal(h.c.view().revoked,true);
    h.tick(2*g.ROTATE_RETRY_MS);assert.equal(await h.c.maybeRotate(),'idle');
  }finally{s2.server.close();}
  const s3=await fakeServer();try{
    const h=harness(s3,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.c.autoConnect();
    s3.rotateNotOwner=true;h.tick(g.POLL_MS);assert.equal(await h.c.maybeRotate(),'NOT-OWNER');
    assert.equal(h.calls().at(-1).cmd,'disconnect --local-only');
    h.tick(10*60*1000);assert.equal(await h.c.maybeRotate(),'idle','no retry storm within the hour');
  }finally{s3.server.close();}
  const s4=await fakeServer();try{
    const h=harness(s4,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.c.autoConnect();
    s4.cookie='';h.tick(g.POLL_MS);assert.equal(await h.c.maybeRotate(),'NO-SESSION');assert.equal(h.c.view().session,'none');
  }finally{s4.server.close();}
});
test('RATE-LIMIT backs off for a minute',async()=>{
  const s=await fakeServer();try{
    const h=harness(s);await h.c.poll();
    const real=s.server.listeners('request')[0];s.server.removeAllListeners('request');
    s.server.on('request',(req,res)=>{req.resume();res.writeHead(429,{'Content-Type':'application/json'});res.end('{"error":"RATE-LIMIT"}');});
    h.tick(g.POLL_MS);assert.equal(await h.c.poll(),'RATE-LIMIT');
    h.tick(g.POLL_MS);assert.equal(await h.c.poll(),'skipped');
    s.server.removeAllListeners('request');s.server.on('request',real);
    h.tick(g.POLL_MS);assert.equal(await h.c.poll(),'ok');
  }finally{s.server.close();}
});
