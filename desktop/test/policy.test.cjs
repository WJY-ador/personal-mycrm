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
const {inAppAllowed,externalHttps,DASHBOARD}=require('../src/policy.cjs');
test('dashboard window keeps the hosted app and the measured login chain in-app',()=>{
 assert.equal(DASHBOARD,'https://personal-mycrm.onrender.com/app');
 for(const url of [DASHBOARD,'https://personal-mycrm.onrender.com/','https://personal-mycrm.onrender.com/login',
  'https://wealthy-technology-63-staging.authkit.app/oauth2/authorize?client_id=client_x&redirect_uri=https%3A%2F%2Fpersonal-mycrm.onrender.com%2Fauth%2Fcallback&response_type=code',
  'https://wealthy-technology-63-staging.authkit.app/?authorization_session_id=01M6D55XBV1KMKTC5RJNSBSDSG&state=s',
  'https://api.workos.com/user_management/authorize?provider=GoogleOAuth&client_id=client_x',
  'https://accounts.google.com/o/oauth2/v2/auth?client_id=x','https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize',
  'https://login.live.com/oauth20_authorize.srf','https://appleid.apple.com/auth/authorize',
  'https://github.com/login/oauth/authorize?client_id=x','https://github.com/login','https://github.com/session','https://github.com/sessions/two-factor',
  'https://personal-mycrm.onrender.com/auth/callback?code=x&state=y'])assert(inAppAllowed(url),url);
});
test('dashboard window refuses everything else in-app',()=>{
 for(const url of ['http://personal-mycrm.onrender.com/app','https://wealthy-technology-63-staging.authkit.app.evil.com/','https://evil.com/?r=https://api.workos.com/',
  'https://user:secret@personal-mycrm.onrender.com/app','https://personal-mycrm.onrender.com:8443/app','javascript:alert(1)','file:///etc/passwd','not a url',
  'https://github.com/WJY-ador/personal-mycrm','https://github.com/loginx','https://google.com/','https://mail.google.com/'])assert(!inAppAllowed(url),url);
});
test('links leaving the dashboard go to the system browser only over https',()=>{
 assert(externalHttps('https://example.com/a?b=1'));
 for(const url of ['http://example.com/','file:///tmp/x','javascript:alert(1)','mailto:a@b.c','https://u:p@example.com/','custom://x'])assert(!externalHttps(url),url);
});
