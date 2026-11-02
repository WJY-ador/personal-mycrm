'use strict';
const path = require('node:path');
const os = require('node:os');
const https = require('node:https');
const HOSTED = 'https://personal-mycrm.onrender.com/';
const RELEASES = 'https://github.com/WJY-ador/personal-mycrm/releases';
function safeExternal(input) {
  try {
    const u = new URL(input);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
    return (u.origin === new URL(HOSTED).origin && u.pathname === '/' && !u.search && !u.hash)
      || (u.origin === 'https://github.com' && /^\/WJY-ador\/personal-mycrm\/releases(?:\/tag\/[A-Za-z0-9._-]+)?\/?$/.test(u.pathname) && !u.search && !u.hash);
  } catch { return false; }
}
// Dashboard window: only the hosted app and the login chain measured on 2026-11-02
// (/login -> AuthKit -> api.workos.com -> provider -> back) load inside the app.
const DASHBOARD = new URL('app', HOSTED).href;
const IN_APP = new Map([
  ['personal-mycrm.onrender.com', () => true],
  ['wealthy-technology-63-staging.authkit.app', () => true],
  ['api.workos.com', () => true],
  ['accounts.google.com', () => true],
  ['login.microsoftonline.com', () => true],
  ['login.live.com', () => true],
  ['appleid.apple.com', () => true],
  // GitHub only for its login pages; any other github.com link opens in the browser.
  ['github.com', p => /^\/(?:login(?:\/|$)|session(?:\/|$)|sessions\/)/.test(p)],
]);
function cleanHttps(input) {
  try {
    const u = new URL(input);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return null;
    return u;
  } catch { return null; }
}
function inAppAllowed(input) {
  const u = cleanHttps(input);
  const rule = u && IN_APP.get(u.hostname);
  return !!rule && rule(u.pathname);
}
function externalHttps(input) { return !!cleanHttps(input); }
function newerVersion(remote, local) {
  const parse = v => /^v?(\d+)\.(\d+)\.(\d+)$/.exec(v || '')?.slice(1).map(Number);
  const a = parse(remote), b = parse(local);
  if (!a || !b) return false;
  for (let i=0;i<3;i++) { if (a[i] !== b[i]) return a[i] > b[i]; }
  return false;
}
function agentHome(platform=process.platform, env=process.env, home=os.homedir()) {
  const p = platform === 'win32' ? path.win32 : path.posix; // target OS separators, not the host's
  if (env.MYCRM_AGENT_HOME) return p.resolve(env.MYCRM_AGENT_HOME.replace(/^~(?=$|[\\/])/, home));
  if (platform === 'darwin') return p.join(home,'Library','Application Support','my-crm-agent');
  if (platform === 'win32') return p.join(env.APPDATA || home,'my-crm-agent');
  return p.join(home,'.local','share','my-crm-agent');
}
function checkUpdate(current) {
  return new Promise((resolve,reject) => {
    const req = https.get('https://api.github.com/repos/WJY-ador/personal-mycrm/releases/latest', {
      headers:{'User-Agent':'MyCRM-Desktop/'+current, 'Accept':'application/vnd.github+json'}
    }, res => {
      if (res.statusCode === 404) { res.resume(); resolve({state:'not-published', url:RELEASES}); return; }
      if (res.statusCode !== 200) { res.resume(); reject(new Error('release-unavailable')); return; }
      let body='';
      res.setEncoding('utf8');
      res.on('data',chunk => { body+=chunk; if (body.length>1024*1024) req.destroy(new Error('release-too-large')); });
      res.on('end',()=> {
        try {
          const j=JSON.parse(body);
          if (j.draft || j.prerelease || !safeExternal(j.html_url)) throw new Error('release-invalid');
          resolve({state:newerVersion(j.tag_name,current)?'available':'current',version:j.tag_name,url:j.html_url});
        } catch { reject(new Error('release-invalid')); }
      });
      res.on('error',reject);
    });
    req.setTimeout(15000,()=>req.destroy(new Error('release-timeout')));
    req.on('error',reject);
  });
}
module.exports={HOSTED,RELEASES,DASHBOARD,safeExternal,inAppAllowed,externalHttps,newerVersion,agentHome,checkUpdate};
