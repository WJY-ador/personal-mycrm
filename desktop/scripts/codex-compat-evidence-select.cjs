'use strict';
const path=require('node:path'), fs=require('node:fs');
const VERSION=/^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$/;
const SHA=/^[0-9a-f]{40}$/;
function selectVerifiedVersions(versions, hasEvidence) {
 if (!Array.isArray(versions)||!versions.length||versions.length>10||typeof hasEvidence!=='function' ||
     versions.some(v=>typeof v!=='string'||!VERSION.test(v))||new Set(versions).size!==versions.length)
  throw new Error('invalid-versions');
 const result=versions.filter(v=>['arm64','x64'].every(arch=>hasEvidence(arch,v)));
 if (!result.length) throw new Error('no-verified-version');
 return result;
}
module.exports={selectVerifiedVersions};
if (require.main===module) {
 try {
  const dir=process.env.MYCRM_COMPAT_EVIDENCE_DIR, sha=process.env.COMPAT_SOURCE;
  if(!dir||!path.isAbsolute(dir)||!SHA.test(sha||''))throw new Error('invalid-evidence');
  const all=JSON.parse(process.env.VERSIONS_JSON);
  const selected=selectVerifiedVersions(all,(arch,v)=>{
   const file=path.join(dir,`codex-probe-${sha}-${arch}-${v}`,'compat-receipt.json');
   try { const info=fs.lstatSync(file); return info.isFile()&&!info.isSymbolicLink()&&info.size<=16384; }
   catch(e) {if(e.code==='ENOENT')return false;throw e;}
  });
  const omitted=all.filter(v=>!selected.includes(v));
  if(omitted.length)process.stderr.write(`::warning::CLI versions without successful probes omitted: ${omitted.join(', ')}\n`);
  process.stdout.write('versions='+JSON.stringify(selected)+'\n');
 }catch(_){process.stderr.write('compatibility probe evidence unavailable\n');process.exitCode=1;}
}
