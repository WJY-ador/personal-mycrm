const {test}=require('node:test');const assert=require('node:assert/strict');
const h=require('../src/handoff.cjs');
const HOSTED='https://personal-mycrm.onrender.com/';
test('challenge is S256 base64url without padding (RFC 7636 appendix B)',()=>{
 assert.equal(h.challengeOf('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
});
test('begin makes a 32-byte verifier, 16-byte state and a 10-minute expiry',()=>{
 const p=h.begin(1000);
 assert.match(p.verifier,/^[A-Za-z0-9_-]{43}$/);assert.match(p.state,/^[A-Za-z0-9_-]{22}$/);assert.match(p.challenge,/^[A-Za-z0-9_-]{43}$/);
 assert.equal(p.challenge,h.challengeOf(p.verifier));assert.equal(p.expiresAt,1000+10*60*1000);
 assert.notEqual(h.begin().state,p.state);
});
test('login URL carries only challenge and state, never the verifier',()=>{
 const p=h.begin();const u=new URL(h.loginUrl(HOSTED,p.challenge,p.state));
 assert.equal(u.origin+u.pathname,'https://personal-mycrm.onrender.com/desktop/login');
 assert.deepEqual([...u.searchParams.keys()],['challenge','state']);
 assert.equal(u.searchParams.get('challenge'),p.challenge);assert.equal(u.searchParams.get('state'),p.state);
 assert(!u.href.includes(p.verifier));
});
const CODE='A'.repeat(43),STATE='s_-1234567890abcdefghi';
const link=(q)=>'mycrm://auth/callback?'+q;
test('deep link parses the server callback',()=>{
 assert.deepEqual(h.parseCallback(link(`code=${CODE}&state=${STATE}`)),{code:CODE,state:STATE});
 assert.deepEqual(h.parseCallback(link(`state=${STATE}&code=${CODE}`)),{code:CODE,state:STATE});
 assert.deepEqual(h.parseCallback(`mycrm://auth/callback/?code=${CODE}&state=${STATE}`),{code:CODE,state:STATE});
});
test('deep link rejects other schemes, paths, extra or repeated parameters and bad characters',()=>{
 for(const raw of [
  `https://auth/callback?code=${CODE}&state=${STATE}`,`mycrmx://auth/callback?code=${CODE}&state=${STATE}`,
  `mycrm://evil/callback?code=${CODE}&state=${STATE}`,`mycrm://auth/other?code=${CODE}&state=${STATE}`,
  link(`code=${CODE}`),link(`state=${STATE}`),link(`code=${CODE}&state=${STATE}&next=https://evil.com`),
  link(`code=${CODE}&code=${CODE}&state=${STATE}`),link(`code=${CODE}&state=${STATE}&state=${STATE}`),
  link(`code=${CODE}%2B&state=${STATE}`),link(`code=${CODE}&state=${STATE}%3C`),link(`code=${CODE}&state=a b${STATE}`),
  link(`code=short&state=${STATE}`),link(`code=${'A'.repeat(129)}&state=${STATE}`),link(`code=${CODE}&state=${'s'.repeat(65)}`),
  `mycrm://auth/callback?code=${CODE}&state=${STATE}#x`,`mycrm://u:p@auth/callback?code=${CODE}&state=${STATE}`,
  link(`code=${CODE}&state=${STATE}`)+'&x='.repeat(400),'not a url','',null,undefined,42,
 ])assert.equal(h.parseCallback(raw),null,String(raw));
});
test('accept checks pending, expiry and state; a wrong state does not count as success',()=>{
 const p={...h.begin(0),state:STATE};const ok={code:CODE,state:STATE};
 assert.equal(h.accept(p,ok,1),'ok');
 assert.equal(h.accept(p,ok,p.expiresAt),'ok');assert.equal(h.accept(p,ok,p.expiresAt+1),'expired');
 assert.equal(h.accept(p,{code:CODE,state:STATE.slice(0,-1)+'j'},1),'state');
 assert.equal(h.accept(p,{code:CODE,state:STATE+'x'},1),'state');
 assert.equal(h.accept(null,ok,1),'none');assert.equal(h.accept(p,null,1),'format');
});
test('claim body is form-encoded with code, verifier and state',()=>{
 const q=new URLSearchParams(h.claimBody(CODE,'v-_1',STATE));
 assert.deepEqual([...q.keys()],['code','verifier','state']);assert.equal(q.get('verifier'),'v-_1');
});
test('deep link is found in launch arguments (Windows first run and second instance)',()=>{
 assert.equal(h.findLink(['C:\\MyCRM.exe','--flag',link(`code=${CODE}&state=${STATE}`)]),link(`code=${CODE}&state=${STATE}`));
 assert.equal(h.findLink(['/usr/bin/electron','.']),null);assert.equal(h.findLink(undefined),null);
});
test('only hosted /login and /desktop/login count as a login start',()=>{
 for(const url of [HOSTED+'login',HOSTED+'login?fresh=1',HOSTED+'desktop/login?challenge=x&state=y'])assert(h.isLoginNav(url,HOSTED),url);
 for(const url of [HOSTED+'app',HOSTED+'loginx',HOSTED+'auth/callback','https://evil.com/login','http://personal-mycrm.onrender.com/login','nope'])assert(!h.isLoginNav(url,HOSTED),url);
});
test('fresh=1 on the intercepted login is passed on to /desktop/login, otherwise not',()=>{
 for(const url of [HOSTED+'login?fresh=1',HOSTED+'login?x=2&fresh=1',HOSTED+'desktop/login?challenge=a&state=b&fresh=1'])assert(h.wantsFresh(url),url);
 for(const url of [HOSTED+'login',HOSTED+'login?fresh=0',HOSTED+'login?fresh=true',HOSTED+'login#fresh=1','nope'])assert(!h.wantsFresh(url),url);
 const p=h.begin();
 const fresh=new URL(h.loginUrl(HOSTED,p.challenge,p.state,true));
 assert.deepEqual([...fresh.searchParams.keys()],['challenge','state','fresh']);assert.equal(fresh.searchParams.get('fresh'),'1');
 assert(!new URL(h.loginUrl(HOSTED,p.challenge,p.state,false)).searchParams.has('fresh'));
});
test('claim request posts the form to /desktop/claim with the desktop header and nothing in the URL',()=>{
 const {url,options}=h.claimRequest(HOSTED,CODE,'V'.repeat(43),STATE);
 assert.equal(url,'https://personal-mycrm.onrender.com/desktop/claim');assert(!url.includes('?'));
 assert.deepEqual(options.extraHeaders.split('\n'),['Content-Type: application/x-www-form-urlencoded','X-MyCRM-Desktop: 1']);
 assert.equal(options.postData.length,1);assert.equal(options.postData[0].type,'rawData');
 const q=new URLSearchParams(options.postData[0].bytes.toString());
 assert.deepEqual(Object.fromEntries(q),{code:CODE,verifier:'V'.repeat(43),state:STATE});
});
test('R-J5: a deep link raises a window at most once per 2 seconds; the first raise always passes',()=>{
 assert.equal(h.FOCUS_GAP_MS,2000);
 let t=50;const raise=h.focusLimiter(h.FOCUS_GAP_MS,()=>t);
 assert.equal(raise(),true,'first');
 t=1500;assert.equal(raise(),false,'inside 2 s');
 t=2049;assert.equal(raise(),false,'a refused raise does not restart the window');
 t=2050;assert.equal(raise(),true,'2 s after the last raise');
 t=2051;assert.equal(raise(),false);
 assert.equal(h.focusLimiter()(),true,'default clock');
});
test('R-J5: main.cjs raises for setup and login links only through the limiter; the link is still handled',()=>{
 const main=require('node:fs').readFileSync(require('node:path').join(__dirname,'..','src','main.cjs'),'utf8');
 const body=(name)=>main.slice(main.indexOf(`function ${name}(`),main.indexOf('\n}',main.indexOf(`function ${name}(`)));
 assert.match(main,/const linkRaise=handoff\.focusLimiter\(\);/);
 assert.match(body('raiseForLink'),/if\(!linkRaise\(\)\)return;showWindow\(\);app\.focus\(\{steal:true\}\);/);
 for(const name of ['setupLink','deepLink']){
  assert.doesNotMatch(body(name),/steal|show\(\)|showDashboard\(\)/,name+' does not raise by itself');
 }
 assert.match(body('setupLink'),/raiseForLink\(show\);[\s\S]*setup-step/);
 assert.match(body('deepLink'),/raiseForLink\(showDashboard\);[\s\S]*handoff\.accept/);
});
