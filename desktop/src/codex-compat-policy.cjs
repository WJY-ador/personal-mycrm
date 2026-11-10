'use strict';
// Verification primitive only. No production key, network fetch, storage or execution grant.
// The caller must atomically persist the returned checkpoint before using a policy.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const VERSION = /^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$/;
const HEX = /^[0-9a-f]{64}$/;
const MAX_BYTES = 16384;
function fail() { throw new Error('invalid-compatibility-policy'); }
function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === keys.slice().sort().join(',');
}
function decode(value) {
  if (typeof value !== 'string' || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) fail();
  const data = Buffer.from(value, 'base64');
  if (data.toString('base64') !== value) fail();
  return data;
}
function version(value) {
  if (typeof value !== 'string') fail();
  const m = VERSION.exec(value);
  if (!m) fail();
  return m.slice(1).map(Number);
}
function less(a,b) { for (let i=0;i<3;i++) { if(a[i]!==b[i]) return a[i]<b[i]; } return false; }
function verifyPolicy(raw, options) {
  if (typeof raw !== 'string' || Buffer.byteLength(raw, 'utf8') > MAX_BYTES || !options) fail();
  const {keys, now, os, arch, appVersion, configSha256, floor} = options;
  if (!Number.isSafeInteger(now) || !exactKeys(floor,['revision','digest']) || !Number.isSafeInteger(floor.revision)
      || floor.revision < 0 || (floor.revision === 0 ? floor.digest !== null : typeof floor.digest !== 'string' || !HEX.test(floor.digest))) fail();
  const currentApp = version(appVersion);
  let e;
  try { e=JSON.parse(raw); } catch { fail(); }
  if (!exactKeys(e,['key_id','payload','signature']) || typeof e.key_id !== 'string'
      || !/^[a-zA-Z0-9_-]{1,64}$/.test(e.key_id) || !keys || !Object.hasOwn(keys,e.key_id)) fail();
  const payload=decode(e.payload), signature=decode(e.signature);
  if (payload.length>MAX_BYTES || signature.length!==64) fail();
  const key=keys[e.key_id];
  if (!(key instanceof crypto.KeyObject) || key.type!=='public' || key.asymmetricKeyType!=='ed25519'
      || !crypto.verify(null,payload,key,signature)) fail();
  let p;
  try { p=JSON.parse(payload.toString('utf8')); } catch { fail(); }
  if (!exactKeys(p,['schema','revision','issued_at','expires_at','os','arch','min_app','source_sha','config_sha256','versions']) || p.schema!==2
      || !Number.isSafeInteger(p.revision) || p.revision<1 || !Number.isSafeInteger(p.issued_at)
      || !Number.isSafeInteger(p.expires_at) || p.issued_at>now || p.expires_at<=now
      || p.expires_at-p.issued_at>90*86400 || p.os!==os || p.arch!==arch
      || typeof p.source_sha !== 'string' || !/^[0-9a-f]{40}$/.test(p.source_sha)
      || typeof configSha256 !== 'string' || !HEX.test(configSha256) || p.config_sha256 !== configSha256
      || less(currentApp,version(p.min_app)) || !Array.isArray(p.versions) || p.versions.length>128) fail();
  for (const v of p.versions) {
    if (!exactKeys(v,['version','native_sha256','host_sha256']) || typeof v.native_sha256 !== 'string'
        || !HEX.test(v.native_sha256) || typeof v.host_sha256 !== 'string' || !HEX.test(v.host_sha256)) fail();
    version(v.version);
  }
  if (new Set(p.versions.map(v=>v.version)).size!==p.versions.length) fail();
  const digest=crypto.createHash('sha256').update(payload).digest('hex');
  if(p.revision<floor.revision || (p.revision===floor.revision && digest!==floor.digest)) fail();
  return {versions:p.versions.map(v=>({...v})),checkpoint:{revision:p.revision,digest}};
}
// This checkpoint provides process-safe local persistence, not protection against
// an attacker deleting the entire state directory. The caller must supply an
// independently protected floor before using this for production authorization.
function acceptPolicy(raw, options, directory) {
  if (typeof directory !== 'string' || !path.isAbsolute(directory)) fail();
  const dirStat = fs.lstatSync(directory);
  if (!dirStat.isDirectory() || dirStat.isSymbolicLink()) fail();
  const lock = path.join(directory, '.policy-checkpoint.lock');
  const checkpoint = path.join(directory, 'policy-checkpoint.json');
  fs.mkdirSync(lock, {mode: 0o700}); // Do not break stale locks automatically.
  let tmp;
  try {
    let floor = options.floor;
    try {
      const entry = fs.lstatSync(checkpoint);
      if (!entry.isFile() || entry.isSymbolicLink()) fail();
      const flags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0);
      const fd = fs.openSync(checkpoint, flags);
      try {
        const st = fs.fstatSync(fd);
        if (!st.isFile() || st.size > 1024 || st.dev !== entry.dev || st.ino !== entry.ino) fail();
        const stored = JSON.parse(fs.readFileSync(fd, 'utf8'));
        if (!exactKeys(stored, ['revision', 'digest'])) fail();
        // The caller's independently protected floor remains authoritative.
        if (stored.revision < floor.revision ||
            (stored.revision === floor.revision && stored.digest !== floor.digest)) fail();
        floor = stored;
      } finally { fs.closeSync(fd); }
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
    const result = verifyPolicy(raw, {...options, floor});
    tmp = path.join(directory, `.policy-${crypto.randomBytes(16).toString('hex')}.tmp`);
    const fd = fs.openSync(tmp, 'wx', 0o600);
    try {
      fs.writeFileSync(fd, JSON.stringify(result.checkpoint));
      fs.fsyncSync(fd);
    } finally { fs.closeSync(fd); }
    fs.renameSync(tmp, checkpoint);
    tmp = undefined;
    // On POSIX, flush the directory entry as well as the file contents.
    if (process.platform !== 'win32') {
      const directoryFd = fs.openSync(directory, fs.constants.O_RDONLY);
      try { fs.fsyncSync(directoryFd); } finally { fs.closeSync(directoryFd); }
    }
    return result;
  } finally {
    if (tmp) { try { fs.unlinkSync(tmp); } catch {} }
    fs.rmdirSync(lock);
  }
}
module.exports={verifyPolicy,acceptPolicy};
