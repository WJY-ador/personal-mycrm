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
test('R-J5: main.cjs raises the dashboard for setup and login links only through the limiter; the link is still handled',()=>{
 const main=require('node:fs').readFileSync(require('node:path').join(__dirname,'..','src','main.cjs'),'utf8');
 const body=(name)=>main.slice(main.indexOf(`function ${name}(`),main.indexOf('\n}',main.indexOf(`function ${name}(`)));
 assert.match(main,/const linkRaise=handoff\.focusLimiter\(\);/);
 assert.match(body('raiseForLink'),/if\(!linkRaise\(\)\)return;showWindow\(\);app\.focus\(\{steal:true\}\);/);
 assert.doesNotMatch(body('deepLink'),/steal|showDashboard\(\);/,'deepLink does not raise by itself');
 assert.match(body('deepLink'),/raiseForLink\(showDashboard\);\r?\n  const step=handoff\.parseSetupLink\(raw\);if\(step\)\{openStep\(step\);return;\}[\s\S]*handoff\.accept/);
 // One window (spec 2026-11-13 §1.1): a mycrm://connection?step=… link shows the dashboard; provider also opens the
 // AI panel (spec 2026-11-18 §1.4, openStep).
 assert.match(body('guard'),/const step=handoff\.parseSetupLink\(url\);\r?\n  if\(step\)\{event\.preventDefault\(\);raiseForLink\(showDashboard\);openStep\(step\);return;\}/);
 assert.doesNotMatch(main,/setup-step|setupLink|function show\(\)/);
});

test('setup step: provider opens the AI panel (#_ai), connect and permits only show the dashboard',()=>{
 const DASH='https://personal-mycrm.onrender.com/app';
 assert.equal(h.AI_PANEL_HASH,'#_ai');
 for(const step of ['connect','permits',null])for(const cur of [DASH,'',DASH+'#_today'])assert.equal(h.setupNavigation(step,cur,DASH),null,String(step));
 // The dashboard document is already open (any hash or query): only the hash changes, no reload.
 for(const cur of [DASH,DASH+'#_today',DASH+'#_setup/pc',DASH+'?x=1#_me',DASH+'#_ai'])assert.deepEqual(h.setupNavigation('provider',cur,DASH),{hash:'#_ai'},cur);
 // Anything else (app start, a login notice page, another path or origin): load the dashboard with the hash.
 for(const cur of ['','about:blank','data:text/html,x','https://personal-mycrm.onrender.com/','https://personal-mycrm.onrender.com/login','https://evil.example/app'])
  assert.deepEqual(h.setupNavigation('provider',cur,DASH),{load:DASH+'#_ai'},cur);
 assert.equal(h.setupNavigation('provider','',DASH+'#_today').load,DASH+'#_ai','the dashboard URL keeps no other hash');
 // The links the web uses (server/ui webchat text.ts) parse to these steps.
 assert.equal(h.parseSetupLink('mycrm://connection?step=provider'),'provider');
 assert.equal(h.parseSetupLink('mycrm://connection?step=connect'),'connect');
});
test('main: every setup link path (running app, page link, new window, link that launched the app) goes through openStep',()=>{
 const main=require('node:fs').readFileSync(require('node:path').join(__dirname,'..','src','main.cjs'),'utf8');
 assert.match(main,/const stepLimit=handoff\.focusLimiter\(\);/);
 const open=/function openStep\(step\)\{[\s\S]*?\n\}/.exec(main)?.[0]||'';
 assert.match(open,/handoff\.setupNavigation\(step,dash\.webContents\.getURL\(\),DASHBOARD\)/);
 assert.match(open,/if\(!nav\|\|!stepLimit\(\)\)return;/,'connect and permits do nothing more; at most once per 2 s');
 // The only script the app runs in the page: a fixed hash, no link text.
 assert.match(open,/if\(nav\.hash\)dash\.webContents\.executeJavaScript\(`location\.hash=\$\{JSON\.stringify\(nav\.hash\)\};`\)\.catch\(\(\)=>\{\}\);/);
 assert.equal((main.match(/executeJavaScript\(/g)||[]).length,1);
 assert.match(open,/else dash\.loadURL\(nav\.load\)\.catch\(\(\)=>\{\}\);/);
 assert.match(main,/setWindowOpenHandler\(\(\{url\}\)=>\{const step=handoff\.parseSetupLink\(url\);if\(step\)\{raiseForLink\(showDashboard\);openStep\(step\);\}else/);
 // Launched by the link (queuedLink): the first load is the dashboard with the AI panel.
 assert.match(main,/const link=queuedLink;queuedLink=null;const step=link\?handoff\.parseSetupLink\(link\):null;\r?\n  if\(link&&!step\)deepLink\(link\);else dash\.loadURL\(handoff\.setupNavigation\(step,'',DASHBOARD\)\?\.load\|\|DASHBOARD\)\.catch\(\(\)=>\{\}\);/);
});
