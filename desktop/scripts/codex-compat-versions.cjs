'use strict';
// Existing policy versions are only probe candidates; they never authorize execution.
const fs=require('node:fs'),path=require('node:path');
const VERSION=/^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$/;
function selectCandidates(recent,policies) {
 if(!Array.isArray(recent)||!Array.isArray(policies)||policies.length>200) throw new Error('invalid-candidates');
 const values=[...recent];
 for(const raw of policies) {
  if(typeof raw!=='string'||Buffer.byteLength(raw)>16384) throw new Error('invalid-policy');
  const env=JSON.parse(raw);
  if(typeof env.payload!=='string'||env.payload.length>22000||!/^[A-Za-z0-9+/]*={0,2}$/.test(env.payload))throw new Error('invalid-policy');
  const body=JSON.parse(Buffer.from(env.payload,'base64').toString('utf8'));
  if(!Array.isArray(body.versions)||body.versions.length>10) throw new Error('invalid-policy');
  for(const entry of body.versions) values.push(entry&&entry.version);
 }
 if(values.some(v=>typeof v!=='string'||!VERSION.test(v))) throw new Error('invalid-version');
 const versions=[...new Set(values)];
 // Do not silently discard an installed version when the probe matrix is full.
 if(!versions.length||versions.length>10) throw new Error('candidate-limit');
 return versions.sort((a,b)=>{const x=a.split('.').map(Number),y=b.split('.').map(Number);return x[0]-y[0]||x[1]-y[1]||x[2]-y[2];});
}
module.exports={selectCandidates};
if(require.main===module){
 try{
  const dir=process.env.MYCRM_PRIOR_POLICIES_DIR;
  if(!dir||!path.isAbsolute(dir))throw new Error('invalid-directory');
  const files=fs.readdirSync(dir,{withFileTypes:true});
  if(files.some(f=>!f.isFile()||!/^darwin-(arm64|x64)-[0-9a-f]{64}\.json$/.test(f.name)))throw new Error('invalid-file');
  const policies=files.map(f=>fs.readFileSync(path.join(dir,f.name),'utf8'));
  const recent=JSON.parse(process.env.MYCRM_RECENT_VERSIONS);
  process.stdout.write('matrix='+JSON.stringify(selectCandidates(recent,policies))+'\n');
 }catch(_){process.stderr.write('compatibility candidate discovery failed\n');process.exitCode=1;}
}
