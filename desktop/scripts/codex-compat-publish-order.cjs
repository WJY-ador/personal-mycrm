'use strict';
const fs=require('node:fs');
function revision(data) {
 if(typeof data!=='string'||Buffer.byteLength(data)>16384)throw new Error('invalid-policy');
 const envelope=JSON.parse(data);
 if(!envelope||typeof envelope.payload!=='string')throw new Error('invalid-policy');
 const raw=Buffer.from(envelope.payload,'base64');
 if(raw.toString('base64')!==envelope.payload)throw new Error('invalid-policy');
 const payload=JSON.parse(raw.toString('utf8'));
 if(!Number.isSafeInteger(payload.revision)||payload.revision<1)throw new Error('invalid-policy');
 return payload.revision;
}
function publishDecision(next,current) {
 const n=revision(next);
 if(current===null)return true;
 const c=revision(current);
 if(n<c)return false;
 if(n===c) {
  if(next!==current)throw new Error('conflicting-revision');
  return false;
 }
 return true;
}
module.exports={publishDecision};
if(require.main===module){
 try{
  const [nextPath,currentPath]=process.argv.slice(2);
  const next=fs.readFileSync(nextPath,'utf8');
  const current=currentPath ? fs.readFileSync(currentPath,'utf8') : null;
  process.stdout.write(publishDecision(next,current)?'publish\n':'skip\n');
 }catch(_){process.stderr.write('invalid or conflicting compatibility policy\n');process.exitCode=1;}
}
