'use strict';
const path = require('node:path');
const os = require('node:os');
const https = require('node:https');
const PRODUCTION = 'https://personal-mycrm.onrender.com/';
// Local E2E only: a loopback server set at build time (-c.extraMetadata.mycrmDevHosted=http://127.0.0.1:8800/)
// or, when running unpackaged (`electron .`), MYCRM_DEV_HOSTED. Release builds carry neither, so they use PRODUCTION.
function hostedBase({pkg={}, env={}, defaultApp=false}={}) {
  const raw = pkg.mycrmDevHosted || (defaultApp ? env.MYCRM_DEV_HOSTED : '');
  if (!raw) return PRODUCTION;
  try {
    const u = new URL(raw);
    if (!['http:','https:'].includes(u.protocol) || u.username || u.password) return PRODUCTION;
    if (!['127.0.0.1','localhost','[::1]'].includes(u.hostname)) return PRODUCTION;
    return u.origin + '/';
  } catch { return PRODUCTION; }
}
let pkg = {};
try { pkg = require('../package.json'); } catch {}
const HOSTED = hostedBase({pkg, env: process.env, defaultApp: !!process.defaultApp});
const RELEASES = 'https://github.com/WJY-ador/personal-mycrm/releases';
function safeExternal(input) {
  try {
    const u = new URL(input);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
    return (u.origin === new URL(HOSTED).origin && u.pathname === '/' && !u.search && !u.hash)
      || (u.origin === 'https://github.com' && /^\/WJY-ador\/personal-mycrm\/releases(?:\/tag\/[A-Za-z0-9._-]+)?\/?$/.test(u.pathname) && !u.search && !u.hash);
  } catch { return false; }
}
// Dashboard window: only the hosted origin loads in-app. Login itself runs in the system browser
// (see handoff.cjs), so no identity-provider host is allowed here; everything else https goes to the browser.
const DASHBOARD = new URL('app', HOSTED).href;
function cleanHttps(input) {
  try {
    const u = new URL(input);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return null;
    return u;
  } catch { return null; }
}
function inAppAllowed(input) {
  try {
    const u = new URL(input);
    return !u.username && !u.password && u.origin === new URL(HOSTED).origin;
  } catch { return false; }
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
// GitHub releases/latest. Called only by updater.cjs, for builds that announce a new release without installing it.
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
// PACKAGE: the packaged package.json (build markers such as mycrmDevHosted and mycrmMacUpdater; updater.cjs).
module.exports={PACKAGE:pkg,HOSTED,PRODUCTION,hostedBase,RELEASES,DASHBOARD,safeExternal,inAppAllowed,externalHttps,newerVersion,agentHome,checkUpdate};
