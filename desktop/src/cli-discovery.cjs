'use strict';
const fs=require('node:fs');
const path=require('node:path');

const MACOS_CLI_DIRS=['.local/bin','.npm-global/bin','/opt/homebrew/bin','/usr/local/bin'];

function findCliCandidates(name,{platform=process.platform,home=osHome(),pathValue=process.env.PATH||'',
  existsSync=fs.existsSync,realpathSync=fs.realpathSync,statSync=fs.statSync,accessSync=fs.accessSync}={}) {
 if(!/^[a-z0-9][a-z0-9-]{0,39}$/i.test(name))throw new TypeError('cli name');
 const dirs=[];
 for(const dir of String(pathValue).split(path.delimiter)){
  if(!path.isAbsolute(dir)||dir==='/'||/(^|\/)\.cmuxterm\/cmux-cli-shims(?:\/|$)/.test(dir)||/(^|\/)\.codex\/tmp(?:\/|$)/.test(dir))continue;
  dirs.push(path.normalize(dir));
 }
 if(platform==='darwin')for(const dir of MACOS_CLI_DIRS){
  dirs.push(path.isAbsolute(dir)?dir:path.join(home,dir));
 }
 const found=[],seen=new Set();
 for(const dir of dirs){
  const candidate=path.join(dir,name);
  try{
   if(!existsSync(candidate))continue;
   const resolved=realpathSync(candidate),st=statSync(resolved);
   if(!path.isAbsolute(resolved)||!st.isFile())continue;
   accessSync(resolved,fs.constants.X_OK);
   if(!seen.has(resolved)){seen.add(resolved);found.push(resolved);}
  }catch{}
 }
 return found;
}

function osHome(){return require('node:os').homedir();}

function parseModelIds(value){
 if(typeof value!=='string')throw new TypeError('models');
 const models=value.split(',').map(model=>model.trim()).filter(Boolean);
 if(!models.length||models.length>20||models.some(model=>!/^[A-Za-z0-9._:/+-]{1,120}$/.test(model))
    ||new Set(models).size!==models.length)throw new TypeError('models');
 return models;
}

module.exports={findCliCandidates,parseModelIds};
