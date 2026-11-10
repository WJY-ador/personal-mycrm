'use strict';
const fs = require('node:fs');
const path = require('node:path');
const NAME = /^darwin-(arm64|x64)-([0-9a-f]{64})\.json$/;
const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
function versionParts(v) {
 if (typeof v !== 'string' || !VERSION.test(v)) throw new Error('invalid-version');
 return v.split('.').map(x => BigInt(x));
}
function less(a,b) { for(let i=0;i<3;i++){ if(a[i]!==b[i]) return a[i]<b[i]; } return false; }
function choosePolicies(items) {
 const result = new Map(), metadata = new Map(), blocked = new Set();
 for (const {name,data} of items) {
  const match=NAME.exec(name);
  if (!match || typeof data !== 'string' || Buffer.byteLength(data)>16384) throw new Error('invalid-policy');
  const env=JSON.parse(data), payload=JSON.parse(Buffer.from(env.payload,'base64').toString('utf8'));
  if (payload.os!=='darwin'||payload.arch!==match[1]||payload.config_sha256!==match[2]||!Array.isArray(payload.versions)) throw new Error('invalid-policy');
  const ver=versionParts(payload.min_app), fingerprint=JSON.stringify(payload.versions);
  const old=metadata.get(name);
  if (blocked.has(name)) continue;
  if (old && old.fingerprint!==fingerprint) {
   result.delete(name); metadata.delete(name); blocked.add(name);
   continue;
  }
  if (!old || less(ver,old.ver)) { metadata.set(name,{ver,fingerprint}); result.set(name,data); }
 }
 if (!result.size) throw new Error('missing-policies');
 if (blocked.size) process.stderr.write(`conflicting compatibility policies skipped: ${blocked.size}\n`);
 return result;
}
module.exports={choosePolicies};
if (require.main===module) {
 try {
  const [src,dst]=process.argv.slice(2);
  if (!path.isAbsolute(src)||!path.isAbsolute(dst)) throw new Error('invalid-path');
  const items=[];
  for (const entry of fs.readdirSync(src,{withFileTypes:true})) {
   if (!entry.isDirectory() || !/^codex-signed-policies-[0-9a-f]{40}$/.test(entry.name)) throw new Error('invalid-artifact');
   for (const child of fs.readdirSync(path.join(src,entry.name),{withFileTypes:true})) {
    if (!child.isFile()) throw new Error('invalid-policy');
    items.push({name:child.name,data:fs.readFileSync(path.join(src,entry.name,child.name),'utf8')});
   }
  }
  fs.mkdirSync(dst,{recursive:false});
  for(const [name,data] of choosePolicies(items)) fs.writeFileSync(path.join(dst,name),data,{flag:'wx'});
 } catch (_) {process.stderr.write('compatibility policy collection failed\n');process.exitCode=1;}
}
