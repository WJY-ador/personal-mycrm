const {test}=require('node:test');const assert=require('node:assert/strict');const path=require('node:path');
const {safeExternal,newerVersion,agentHome,HOSTED}=require('../src/policy.cjs');
test('external destinations reject injection, credentials, redirects and foreign origins',()=>{
 assert(safeExternal(HOSTED));assert(safeExternal('https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.1'));
 for(const url of ['file:///tmp/x','javascript:alert(1)','http://personal-mycrm.onrender.com/','https://evil.com/','https://personal-mycrm.onrender.com.evil.com/','https://user:secret@personal-mycrm.onrender.com/','https://github.com/WJY-ador/personal-mycrm/releases?x=1','https://github.com/other/project/releases','https://personal-mycrm.onrender.com/path'])assert(!safeExternal(url),url);
});
test('semver comparison rejects prereleases and never offers downgrade',()=>{
 assert(newerVersion('v0.1.10','0.1.9'));assert(!newerVersion('v0.1.1-beta','0.1.0'));assert(!newerVersion('v0.1.0','0.1.1'));assert(!newerVersion('0.1.1','0.1.1'));
});
test('agent home remains outside install directory across upgrades',()=>{
 assert.equal(agentHome('darwin',{},'/Users/test'),'/Users/test/Library/Application Support/my-crm-agent');
 assert.equal(agentHome('win32',{APPDATA:'/user/appdata'},'/user'),path.win32.join('/user/appdata','my-crm-agent'));
 assert.equal(agentHome('darwin',{MYCRM_AGENT_HOME:'~/existing'},'/Users/test'),'/Users/test/existing');
});
