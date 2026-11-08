const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {findCliCandidates}=require('../src/cli-discovery.cjs');
const {constants}=require('node:fs');

function fixture(files,nonExecutable=[]){
 const existing=new Set([...files,...nonExecutable].map(file=>path.resolve(file)));
 const executable=new Set(files.map(file=>path.resolve(file)));
 return {
  existsSync:file=>existing.has(path.resolve(file)),
  realpathSync:file=>path.resolve(file),
  statSync:file=>({isFile:()=>executable.has(path.resolve(file))}),
  accessSync:(file,mode)=>{if(!executable.has(path.resolve(file))||mode!==constants.X_OK)throw new Error('not executable');}
 };
}

test('discovers executable Codex candidates from GUI PATH and standard macOS locations',{skip:process.platform==='win32'},()=>{
 const home='/Users/tester';
 const pathDir='/opt/custom/bin';
 const files=[`${pathDir}/codex`,`${home}/.local/bin/codex`,`${home}/.npm-global/bin/codex`,`/opt/homebrew/bin/codex`];
 const found=findCliCandidates('codex',{platform:'darwin',home,pathValue:`${pathDir}:/usr/bin`,...fixture(files)});
 assert.deepEqual(found,files);
});

test('ignores current-directory, cmux shim, missing, non-executable and duplicate candidates',{skip:process.platform==='win32'},()=>{
 const home='/Users/tester';
 const files=[`/opt/custom/bin/codex`,`${home}/.local/bin/codex`];
 const found=findCliCandidates('codex',{platform:'darwin',home,
  pathValue:`.:/Users/tester/.cmuxterm/cmux-cli-shims/session:/opt/custom/bin:/opt/custom/bin`,...fixture(files,[`/bad/bin/codex`])});
 assert.deepEqual(found,files);
});

test('discovers executable candidates from Windows PATH and rejects relative entries',{skip:process.platform!=='win32'},()=>{
 const home='C:\\Users\\tester';
 const binary='C:\\tools\\bin\\codex';
 const found=findCliCandidates('codex',{platform:'win32',home,pathValue:'relative;C:\\tools\\bin;C:\\tools\\bin',...fixture([binary])});
 assert.deepEqual(found,[binary]);
});

test('parses explicit Codex model IDs and rejects unknown-shaped or duplicate values',()=>{
 const {parseModelIds}=require('../src/cli-discovery.cjs');
 assert.deepEqual(parseModelIds('model-a, model:b'),['model-a','model:b']);
 for(const value of ['', 'model id', 'bad\nmodel', 'same,same'])assert.throws(()=>parseModelIds(value),/models/);
});
