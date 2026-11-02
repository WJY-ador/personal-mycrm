const {test}=require('node:test');const assert=require('node:assert/strict');const path=require('node:path');
const {safeExternal,newerVersion,agentHome,HOSTED}=require('../src/policy.cjs');
test('external destinations reject injection, credentials, redirects and foreign origins',()=>{
 assert(safeExternal(HOSTED));assert(safeExternal('https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.1'));
 for(const url of ['file:///tmp/x','javascript:alert(1)','http://personal-mycrm.onrender.com/','https://evil.com/','https://personal-mycrm.onrender.com.evil.com/','https://user:secret@personal-mycrm.onrender.com/','https://github.com/WJY-ador/personal-mycrm/releases?x=1','https://github.com/other/project/releases','https://personal-mycrm.onrender.com/path'])assert(!safeExternal(url),url);
});
test('semver comparison rejects prereleases and never offers downgrade',()=>{
 assert(newerVersion('v0.1.10','0.1.9'));assert(!newerVersion('v0.1.1-beta','0.1.0'));assert(!newerVersion('v0.1.0','0.1.1'));assert(!newerVersion('0.1.1','0.1.1'));
});
test('release tag equal to the installed version is not an update; the next patch is',()=>{
 assert(!newerVersion('v0.1.1','0.1.1'));assert(newerVersion('v0.1.2','0.1.1'));
});
test('agent home remains outside install directory across upgrades',()=>{
 assert.equal(agentHome('darwin',{},'/Users/test'),'/Users/test/Library/Application Support/my-crm-agent');
 assert.equal(agentHome('win32',{APPDATA:'/user/appdata'},'/user'),path.win32.join('/user/appdata','my-crm-agent'));
 assert.equal(agentHome('darwin',{MYCRM_AGENT_HOME:'~/existing'},'/Users/test'),'/Users/test/existing');
});
const {inAppAllowed,externalHttps,DASHBOARD,hostedBase,PRODUCTION}=require('../src/policy.cjs');
test('dashboard window keeps only the hosted origin in-app',()=>{
 assert.equal(DASHBOARD,'https://personal-mycrm.onrender.com/app');
 for(const url of [DASHBOARD,'https://personal-mycrm.onrender.com/','https://personal-mycrm.onrender.com/login',
  'https://personal-mycrm.onrender.com/desktop/claim','https://personal-mycrm.onrender.com/auth/callback?code=x&state=y'])assert(inAppAllowed(url),url);
});
test('identity providers are no longer in-app; login runs in the system browser',()=>{
 for(const url of ['https://wealthy-technology-63-staging.authkit.app/oauth2/authorize?client_id=client_x',
  'https://api.workos.com/user_management/authorize?provider=GoogleOAuth&client_id=client_x',
  'https://accounts.google.com/o/oauth2/v2/auth?client_id=x','https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize',
  'https://login.live.com/oauth20_authorize.srf','https://appleid.apple.com/auth/authorize',
  'https://github.com/login/oauth/authorize?client_id=x','https://github.com/login','https://github.com/session'])assert(!inAppAllowed(url),url);
});
test('dashboard window refuses everything else in-app',()=>{
 for(const url of ['http://personal-mycrm.onrender.com/app','https://personal-mycrm.onrender.com.evil.com/','https://evil.com/?r=https://personal-mycrm.onrender.com/',
  'https://user:secret@personal-mycrm.onrender.com/app','https://personal-mycrm.onrender.com:8443/app','javascript:alert(1)','file:///etc/passwd','not a url',
  'https://github.com/WJY-ador/personal-mycrm','https://google.com/','mycrm://auth/callback?code=x&state=y'])assert(!inAppAllowed(url),url);
});
test('release builds always use production; a dev server must be loopback',()=>{
 assert.equal(hostedBase(),PRODUCTION);
 assert.equal(hostedBase({env:{MYCRM_DEV_HOSTED:'http://127.0.0.1:8800'}}),PRODUCTION); // packaged: env ignored
 assert.equal(hostedBase({env:{MYCRM_DEV_HOSTED:'http://127.0.0.1:8800'},defaultApp:true}),'http://127.0.0.1:8800/');
 assert.equal(hostedBase({pkg:{mycrmDevHosted:'http://localhost:8800/x'}}),'http://localhost:8800/');
 for(const raw of ['https://evil.com/','http://127.0.0.1.evil.com:8800/','http://u:p@127.0.0.1:8800/','file:///tmp/x','nope'])
  assert.equal(hostedBase({pkg:{mycrmDevHosted:raw}}),PRODUCTION,raw);
});
test('links leaving the dashboard go to the system browser only over https',()=>{
 assert(externalHttps('https://example.com/a?b=1'));
 for(const url of ['http://example.com/','file:///tmp/x','javascript:alert(1)','mailto:a@b.c','https://u:p@example.com/','custom://x'])assert(!externalHttps(url),url);
});
