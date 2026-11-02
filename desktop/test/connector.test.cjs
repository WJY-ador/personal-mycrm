// PC connection flow against a fake server (contract v1) and a fake sidecar process: the token must reach the
// sidecar's stdin and nowhere else (sidecar stdout, app log, notifications, renderer view, saved record, request URLs).
const {test}=require('node:test');const assert=require('node:assert/strict');
const http=require('node:http');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const {spawn}=require('node:child_process');
const g=require('../src/grants.cjs');const {Connector,ConnectError}=require('../src/connector.cjs');
const DEVICE='imp_dev'+'D'.repeat(40),MIGRATION='mig_tok'+'M'.repeat(40),ROTATED='imp_rot'+'R'.repeat(40),AUTO='imp_aut'+'A'.repeat(40);
const TOKENS=[DEVICE,MIGRATION,ROTATED,AUTO];
// Fake sidecar: records what arrives on stdin (the "key store"), writes config.json like `connect`, prints a fixed line.
const SIDECAR=`
const fs=require('node:fs'),path=require('node:path');const [home,...args]=process.argv.slice(2);let input='';
process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{
  fs.appendFileSync(path.join(home,'calls.log'),JSON.stringify({cmd:args.join(' '),stdin:input})+'\\n');
  if(process.env.FAKE_FAIL==='1'){console.log('자격 증명 저장소에 쓰지 못했어요.');process.exit(1);}
  if(args[0]==='connect'){const t=input.trim();fs.writeFileSync(path.join(home,'config.json'),JSON.stringify({source_instance_id:'src_'+t.slice(4,7),device_label:'Studio',token_expires_at:t.startsWith('imp_rot')?'2027-12-01T00:00:00Z':(process.env.FAKE_EXPIRES||'2027-06-01T00:00:00Z')}));console.log('연결했어요(서버 확인 완료).');}
  else if(args[0]==='disconnect'){fs.writeFileSync(path.join(home,'config.json'),JSON.stringify({source_instance_id:null}));console.log('로컬 업로드 토큰: 제거함');}
  else console.log('이관 토큰을 저장했어요.');
});`;
function fakeServer(){
  const s={sessions:{'sess-1':'u1','sess-2':'u2'},inst:{},grants:[],requests:[],n:0,override:null};
  const send=(res,status,obj,headers={})=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store',...headers});res.end(JSON.stringify(obj));};
  const err=(res,status,code)=>send(res,status,{code,msg:'m',action:'a'});
  const view=i=>({installation_id:i.id,revoked:i.revoked,device:i.device?{device_id:i.device.id,label:i.client_name,active:i.device.active}:null});
  s.server=http.createServer((req,res)=>{
    let raw='';req.on('data',c=>raw+=c);req.on('end',()=>{
      const url=new URL(req.url,'http://x');const body=raw?JSON.parse(raw):null;
      s.requests.push({method:req.method,path:url.pathname,query:url.search,cookie:req.headers.cookie,desk:req.headers['x-mycrm-desktop'],body});
      if(s.override)return s.override(req,res);
      if(req.headers['x-mycrm-desktop']!=='1')return err(res,403,'DESKTOP-HEADER');
      const user=s.sessions[(req.headers.cookie||'').replace('crm_session=','')];if(!user)return err(res,401,'UNAUTHORIZED');
      const own=id=>{const i=s.inst[id];if(!i)return [404,'INSTALLATION-UNKNOWN'];if(i.owner!==user)return [403,'NOT-OWNER'];return [0,i];};
      if(url.pathname==='/desktop/installations'){
        if(body.installation_id){const [st,i]=own(body.installation_id);if(st)return err(res,st,i);i.client_name=body.client_name;return send(res,200,{...view(i),client_name:i.client_name,os:body.os,account_label:user+'@example.com',poll_seconds:30});}
        const i={id:'di_'+String(++s.n).padStart(24,'0'),owner:user,client_name:body.client_name,revoked:false,device:null};s.inst[i.id]=i;
        return send(res,200,{...view(i),client_name:i.client_name,os:body.os,account_label:user+'@example.com',poll_seconds:30});
      }
      if(url.pathname==='/desktop/grants'){const [st,i]=own(url.searchParams.get('installation'));if(st)return err(res,st,i);
        return send(res,200,{installation:view(i),grants:s.grants.filter(x=>x.state==='waiting'&&x.inst===i.id).map(x=>({grant_id:x.id,scope:x.scope,expires_at:'2026-11-02T00:10:00Z'})),poll_seconds:30});}
      const m=/^\/desktop\/grants\/([^/]+)\/redeem$/.exec(url.pathname);
      if(m){const gr=s.grants.find(x=>x.id===m[1]);if(!gr)return err(res,404,'NOT-FOUND');if(gr.owner!==user)return err(res,403,'NOT-OWNER');
        if(gr.inst!==body.installation_id)return err(res,404,'INSTALLATION-UNKNOWN');if(gr.state!=='waiting')return err(res,409,'GRANT-USED');gr.state='delivered';
        const i=s.inst[gr.inst];
        if(gr.scope==='migration')return send(res,200,{grant_id:gr.id,scope:'migration',token:MIGRATION,device_id:null,device_label:null,account_label:user+'@example.com',token_expires_at:'2026-11-09T00:00:00Z'});
        if(!i.device||!i.device.active){i.device={id:'is_'+(++s.n),active:true};i.revoked=false;}
        return send(res,200,{grant_id:gr.id,scope:'device',token:DEVICE,device_id:i.device.id,device_label:i.client_name,account_label:user+'@example.com',token_expires_at:'2027-01-31T00:00:00Z'});}
      if(url.pathname==='/desktop/device/auto'||url.pathname==='/desktop/device/rotate'){
        const [st,i]=own(body.installation_id);if(st)return err(res,st,i);
        if(i.revoked||(i.device&&!i.device.active))return err(res,409,'DEVICE-REVOKED');
        if(url.pathname.endsWith('rotate')){if(!i.device)return err(res,404,'NOT-FOUND');return send(res,200,{token:ROTATED,device_id:i.device.id,device_label:i.client_name,account_label:user+'@example.com',token_expires_at:'2027-12-01T00:00:00Z'});}
        const created=!i.device;if(created)i.device={id:'is_'+(++s.n),active:true};
        return send(res,200,{token:AUTO,device_id:i.device.id,device_label:i.client_name,account_label:user+'@example.com',token_expires_at:'2027-01-31T00:00:00Z',created});
      }
      err(res,404,'NOT-FOUND');
    });
  });
  s.grant=(scope,instId,owner='u1')=>{const x={id:'tg_'+String(++s.n).padStart(24,'0'),scope,inst:instId,owner,state:'waiting'};s.grants.push(x);return x;};
  s.count=p=>s.requests.filter(r=>r.path===p).length;
  return new Promise(r=>s.server.listen(0,'127.0.0.1',()=>{s.base=`http://127.0.0.1:${s.server.address().port}/`;r(s);}));
}
function nodeRequest(s){
  return (method,url,body)=>new Promise(resolve=>{
    const headers={...g.HEADERS};if(s.cookie)headers.Cookie='crm_session='+s.cookie;
    const req=http.request(url,{method,headers},res=>{let b='';res.on('data',c=>b+=c);res.on('end',()=>{let p=null;try{p=JSON.parse(b);}catch{}resolve({status:res.statusCode,body:p,retryAfter:res.headers['retry-after']});});});
    req.on('error',()=>resolve({status:0,body:null}));req.end(body==null?undefined:JSON.stringify(body));
  });
}
function harness(s,{fail=false,expires,dir,stored=null}={}){
  dir=dir||fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-a3-'));const script=path.join(dir,'sidecar.cjs');fs.writeFileSync(script,SIDECAR);
  const h={dir,logs:[],notices:[],stdout:'',busy:false,ready:true,stored};if(s.cookie===undefined)s.cookie='sess-1';
  const command=(args,input)=>new Promise(resolve=>{
    const child=spawn(process.execPath,[script,dir,...args],{env:{...process.env,FAKE_FAIL:fail?'1':'0',FAKE_EXPIRES:expires||''},stdio:['pipe','pipe','pipe']});
    let out='';child.stdout.on('data',c=>out+=c);child.stderr.on('data',c=>out+=c);
    child.on('close',code=>{h.stdout+=out;resolve({code,detail:code?out.trim():null});});child.stdin.end(input?input+'\n':'');
  });
  const connection=()=>{try{const c=JSON.parse(fs.readFileSync(path.join(dir,'config.json'),'utf8'));return {connected:!!c.source_instance_id,expires:c.token_expires_at||null,deviceLabel:c.device_label||''};}catch{return {connected:false,expires:null,deviceLabel:''};}};
  let clock=Date.parse('2026-11-02T00:00:00Z');
  h.c=new Connector({hosted:s.base,request:nodeRequest(s),
    store:{load:()=>h.stored,save:r=>{h.stored=JSON.stringify(r);}},
    install:(scope,token)=>command(g.sidecarArgs(scope,s.base),token),forgetLocal:()=>command(['disconnect','--local-only']),
    exclusive:async fn=>{if(h.busy)throw new Error('busy');h.busy=true;try{return await fn();}finally{h.busy=false;}},
    canDeliver:()=>h.ready&&!h.busy,connection,notify:n=>h.notices.push(n),log:(...a)=>h.logs.push(a),
    client:{client_name:'Studio',os:'darwin'},now:()=>clock});
  h.tick=ms=>{clock+=ms;};h.next=()=>h.tick(g.POLL_MS);
  h.calls=()=>{try{return fs.readFileSync(path.join(dir,'calls.log'),'utf8').trim().split('\n').map(JSON.parse);}catch{return [];}};
  h.inst=()=>JSON.parse(h.stored).installationId;
  h.lock=fn=>h.c.exclusive(fn);   // autoConnect runs under the app lock in main
  h.assertNoLeak=()=>{
    const visible=JSON.stringify([h.logs,h.notices,h.c.view(),h.stored])+h.stdout+JSON.stringify(s.requests.map(r=>[r.path,r.query,r.body]));
    for(const t of TOKENS)assert(!visible.includes(t),'token leaked');
    for(const f of fs.readdirSync(dir).filter(n=>n!=='calls.log'&&n!=='sidecar.cjs'))for(const t of TOKENS)assert(!fs.readFileSync(path.join(dir,f),'utf8').includes(t),'token in '+f);
  };
  return h;
}
async function withServer(fn){const s=await fakeServer();try{await fn(s);}finally{s.server.close();}}

test('poll registers the installation, redeems a device grant, hands the token to sidecar stdin only, and notifies',()=>withServer(async s=>{
  const h=harness(s);
  assert.equal(await h.c.poll('timer'),'ok');
  assert.deepEqual(s.requests[0].body,{client_name:'Studio',os:'darwin'});
  const id=h.inst();assert.match(id,/^di_\d{24}$/);
  s.grant('device',id);h.next();assert.equal(await h.c.poll('timer'),'ok');
  assert.deepEqual(h.calls(),[{cmd:`connect --server ${s.base} --token-stdin`,stdin:DEVICE+'\n'}]);
  assert.deepEqual(h.notices,[{title:'연결됐어요',body:'u1@example.com · Studio'}]);
  assert.equal(s.grants[0].state,'delivered');
  assert(s.requests.every(r=>r.desk==='1'&&r.cookie==='crm_session=sess-1'));
  assert.deepEqual(s.requests.find(r=>r.path.endsWith('/redeem')).body,{installation_id:id});
  assert.deepEqual(h.c.view(),{session:'ok',revoked:false,registered:true});
  h.assertNoLeak();
  // Next app start: the saved id is sent again (upsert), no second installation.
  const again=harness(s,{dir:h.dir,stored:h.stored});await again.c.poll();
  assert.deepEqual(s.requests.filter(r=>r.path==='/desktop/installations').at(-1).body,{client_name:'Studio',os:'darwin',installation_id:id});
  assert.equal(Object.keys(s.inst).length,1);
}));
test('migration grant goes to `migrate login --token-stdin`; a sidecar failure says to update the app',()=>withServer(async s=>{
  const h=harness(s);await h.c.poll();s.grant('migration',h.inst());h.next();await h.c.poll();
  assert.deepEqual(h.calls(),[{cmd:`migrate login --server ${s.base} --token-stdin`,stdin:MIGRATION+'\n'}]);
  assert.deepEqual(h.notices,[{title:'이관 토큰을 받았어요',body:'u1@example.com'}]);h.assertNoLeak();
  const f=harness(s,{fail:true});await f.c.poll();s.grant('migration',f.inst());f.next();await f.c.poll();
  assert.deepEqual(f.notices,[{title:'이관 토큰을 저장하지 못했어요',body:'앱을 최신 버전으로 업데이트한 뒤 대화에서 다시 요청해 주세요.'}]);f.assertNoLeak();
}));
test('no redeem while the sidecar cannot take a token: the grant stays waiting',()=>withServer(async s=>{
  const h=harness(s);await h.c.poll();s.grant('device',h.inst());
  h.ready=false;h.next();await h.c.poll();
  h.ready=true;h.busy=true;h.next();await h.c.poll();h.busy=false;
  assert.equal(s.requests.filter(r=>r.path.endsWith('/redeem')).length,0);assert.equal(s.grants[0].state,'waiting');assert.equal(h.calls().length,0);
  h.next();await h.c.poll();assert.equal(s.grants[0].state,'delivered');
}));
test('without a session: no registration, sign-in state, spaced focus polls, auto asks for [로그인]',()=>withServer(async s=>{
  s.cookie='';const h=harness(s);
  assert.equal(await h.c.poll(),'no-installation');assert.equal(h.c.view().session,'none');assert.equal(h.stored,null);
  await h.c.poll('focus');h.tick(3000);await h.c.poll('focus');h.tick(3000);await h.c.poll('focus');
  assert.equal(s.requests.length,1);
  await assert.rejects(h.lock(()=>h.c.autoConnect()),e=>e instanceof ConnectError&&e.message==='login');
}));
test('account switch on this PC (M3): NOT-OWNER removes the old device token, registers again, then connects this account',()=>withServer(async s=>{
  const h=harness(s);await h.c.poll();await h.lock(()=>h.c.autoConnect());const old=h.inst();
  s.cookie='sess-2';h.next();assert.equal(await h.c.poll(),'ok');
  assert.notEqual(h.inst(),old);assert.equal(s.inst[h.inst()].owner,'u2');
  assert.equal(h.calls().at(-1).cmd,'disconnect --local-only');assert.equal(JSON.parse(h.stored).forget,false);
  assert.equal(h.c.needsAuto(),true);
  await h.lock(()=>h.c.autoConnect());
  assert.equal(h.calls().at(-1).stdin,AUTO+'\n');assert.equal(h.c.needsAuto(),false);
  assert.equal(s.inst[h.inst()].device.active,true);
  // Login poll after a switch: the saved id belongs to the other account, so it registers without the id.
  const u2=h.inst();s.cookie='sess-1';h.next();await h.c.poll('login');
  const regs=s.requests.filter(r=>r.path==='/desktop/installations');
  assert.equal(regs.at(-2).body.installation_id,u2);assert.equal(regs.at(-1).body.installation_id,undefined);assert.equal(s.inst[h.inst()].owner,'u1');
  h.assertNoLeak();
}));
test('auto connection: only on request; lost token gets the same device; revoked or released PC is not reconnected',()=>withServer(async s=>{
  const h=harness(s);await h.c.poll();
  assert.equal(s.count('/desktop/device/auto'),0,'login alone creates no device');
  assert.equal(h.c.needsAuto(),true);await h.lock(()=>h.c.autoConnect());assert.equal(h.c.needsAuto(),false);
  assert.deepEqual(s.requests.find(r=>r.path==='/desktop/device/auto').body,{installation_id:h.inst(),client_name:'Studio',os:'darwin'});
  const dev=s.inst[h.inst()].device.id;
  fs.rmSync(path.join(h.dir,'config.json'));await h.lock(()=>h.c.autoConnect());assert.equal(s.inst[h.inst()].device.id,dev,'same device');
  // Released in a conversation (server) — and the local token is gone: no automatic reconnection.
  s.inst[h.inst()].revoked=true;s.inst[h.inst()].device.active=false;fs.rmSync(path.join(h.dir,'config.json'));
  await assert.rejects(h.lock(()=>h.c.autoConnect()),e=>e.message==='revoked');
  assert.equal(h.c.view().revoked,true);
  const autos=s.count('/desktop/device/auto');await assert.rejects(h.lock(()=>h.c.autoConnect()),e=>e.message==='revoked');
  assert.equal(s.count('/desktop/device/auto'),autos,'no server call while revoked');
  // A conversation reconnect (redeem) lifts it.
  s.grant('device',h.inst());h.next();await h.c.poll();
  assert.equal(h.c.view().revoked,false);assert.equal(s.inst[h.inst()].revoked,false);
  // Disconnecting in this app is a release too.
  h.c.released();fs.rmSync(path.join(h.dir,'config.json'));await assert.rejects(h.lock(()=>h.c.autoConnect()),e=>e.message==='revoked');
  h.c.manualConnected();await h.lock(()=>h.c.autoConnect());
  h.assertNoLeak();
}));
test('session rotate 30 days before expiry; NOT-FOUND, DEVICE-REVOKED, NOT-OWNER and no session are handled',async()=>{
  await withServer(async s=>{
    const h=harness(s,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.lock(()=>h.c.autoConnect());
    h.next();await h.c.poll();
    assert.equal(h.calls().at(-1).stdin,ROTATED+'\n');
    assert.deepEqual(s.requests.find(r=>r.path==='/desktop/device/rotate').body,{installation_id:h.inst()});
    h.tick(2*g.ROTATE_RETRY_MS);await h.c.poll();assert.equal(s.count('/desktop/device/rotate'),1,'new expiry is far away');
    h.assertNoLeak();
  });
  await withServer(async s=>{   // token pasted by hand: this installation has no device
    const h=harness(s,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();
    fs.writeFileSync(path.join(h.dir,'config.json'),JSON.stringify({source_instance_id:'src_manual',token_expires_at:'2026-11-20T00:00:00Z'}));
    h.next();assert.equal(await h.c.maybeRotate(),'NOT-FOUND');
    h.tick(2*g.ROTATE_RETRY_MS);assert.equal(await h.c.maybeRotate(),'idle','no retry for a day');
  });
  await withServer(async s=>{
    const h=harness(s,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.lock(()=>h.c.autoConnect());
    s.inst[h.inst()].revoked=true;s.inst[h.inst()].device.active=false;h.next();assert.equal(await h.c.maybeRotate(),'DEVICE-REVOKED');
    h.tick(2*g.ROTATE_RETRY_MS);assert.equal(await h.c.maybeRotate(),'idle');
  });
  await withServer(async s=>{
    const h=harness(s,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.lock(()=>h.c.autoConnect());
    s.inst[h.inst()].owner='u2';h.next();assert.equal(await h.c.maybeRotate(),'NOT-OWNER');
    assert.equal(h.calls().at(-1).cmd,'disconnect --local-only');
    h.tick(10*60*1000);assert.equal(await h.c.maybeRotate(),'idle','no retry storm within the hour');
  });
  await withServer(async s=>{
    const h=harness(s,{expires:'2026-11-20T00:00:00Z'});await h.c.poll();await h.lock(()=>h.c.autoConnect());
    s.cookie='';h.next();assert.equal(await h.c.maybeRotate(),'NO-SESSION');assert.equal(h.c.view().session,'none');
  });
});
test('RATE-LIMIT backs off for Retry-After seconds',()=>withServer(async s=>{
  const h=harness(s);await h.c.poll();
  s.override=(req,res)=>{res.writeHead(429,{'Content-Type':'application/json','Retry-After':'120'});res.end('{"code":"RATE-LIMIT","msg":"m","action":"a"}');};
  h.next();assert.equal(await h.c.poll(),'RATE-LIMIT');
  h.tick(90*1000);assert.equal(await h.c.poll(),'skipped');
  s.override=null;h.tick(31*1000);assert.equal(await h.c.poll(),'ok');
}));
