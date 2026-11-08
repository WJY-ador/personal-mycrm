// Tests for consent-key-store.cjs (desktop-side storage of the consent signing keypair).
// Synthetic data only: every key is generated in-process for this test and discarded.
// No Electron app, no real userData, no network. Every file lives in a fresh fs.mkdtemp
// directory under os.tmpdir() that is removed after its test.
//
// FAKE, NOT A SECURITY IMPLEMENTATION: fakeSafeStorage below XORs bytes with a fixed test
// constant. It only stands in for Electron safeStorage so the module's control flow can be
// observed. It gives no confidentiality and no integrity. Never copy it into production code.
//
// Contract pinned by these tests (the module does not exist yet):
//  loadOrCreateKeyPair({safeStorage, filePath, keyGenerator?}) -> {publicKey, privateKey}
//   - Returns Ed25519 KeyObjects that belong together.
//   - keyGenerator defaults to () => crypto.generateKeyPairSync('ed25519').
//   - May be sync or async. Tests await the result, so a sync throw counts as a refusal.
//   - The module must not require('electron'). safeStorage is always injected.
//   - Fail closed (throw) unless safeStorage.isEncryptionAvailable() returns exactly true.
//     If safeStorage.getSelectedStorageBackend exists (Linux), its value must be on the allowlist
//     gnome_libsecret, kwallet, kwallet5, kwallet6. basic_text, unknown, any other value, or a
//     throw means fail closed. If the method is absent (macOS, Windows), availability decides.
//     These checks run before keyGenerator, encryptString or decryptString is called.
//   - Key file: UTF-8 JSON with exactly {"v":1,"alg":"ed25519","ciphertext":"<base64>"}.
//     ciphertext is canonical base64 of the exact Buffer that safeStorage.encryptString returned.
//     File mode 0600 on POSIX. No temp file is left next to it.
//   - An existing file is never overwritten or regenerated. Unreadable, malformed, tampered or
//     undecryptable content means throw, keyGenerator not called, file left byte-identical.
//   - Every single-bit change in the ciphertext is rejected. The decrypted plaintext must be
//     self-checking (for example it carries the public key and is compared canonically), so a
//     tampered file never yields a different key silently.
//   - Error messages never contain private key material.
//
// Run: node --test test/consent-key-store.test.cjs   (from desktop/)
const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const store=require('../src/consent-key-store.cjs');

// FAKE ONLY. A fixed XOR byte so that a "restart" with a fresh fake decrypts the same file,
// the way a real OS keychain would. This is not encryption.
const FAKE_XOR_BYTE=0x5a;
const fakeXor=(buf)=>Buffer.from(Buffer.from(buf).map((b)=>b^FAKE_XOR_BYTE));

function fakeSafeStorage({available=true,backend,encrypt,decrypt}={}){
 const calls={isEncryptionAvailable:0,getSelectedStorageBackend:0,encryptIn:[],encryptOut:[],decryptIn:[]};
 const s={
  calls,
  isEncryptionAvailable(){
   calls.isEncryptionAvailable++;
   return typeof available==='function'?available():available;
  },
  encryptString(plain){
   calls.encryptIn.push(plain);
   const out=encrypt?encrypt(plain):(()=>{
    assert.equal(typeof plain,'string','encryptString takes a string');
    return fakeXor(Buffer.from(plain,'utf8'));
   })();
   calls.encryptOut.push(out);
   return out;
  },
  decryptString(buf){
   calls.decryptIn.push(buf);
   if(decrypt)return decrypt(buf);
   assert(Buffer.isBuffer(buf),'decryptString takes a Buffer');
   return fakeXor(buf).toString('utf8');
  },
 };
 if(backend!==undefined){
  s.getSelectedStorageBackend=()=>{
   calls.getSelectedStorageBackend++;
   return typeof backend==='function'?backend():backend;
  };
 }
 return s;
}

function spyGenerator(impl=()=>crypto.generateKeyPairSync('ed25519')){
 const g=()=>{const r=impl();g.results.push(r);return r;};
 g.results=[];
 return g;
}

async function tempDir(t){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-key-store-test-'));
 t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 return dir;
}
const keyFile=(dir)=>path.join(dir,'consent-key.json');
const load=async(opts)=>store.loadOrCreateKeyPair(opts);

const pkcs8=(k)=>k.export({type:'pkcs8',format:'der'});
const spki=(k)=>k.export({type:'spki',format:'der'});
const privatePem=(k)=>k.export({type:'pkcs8',format:'pem'});

function assertEd25519Pair(pair){
 assert(pair&&typeof pair==='object');
 assert.equal(pair.publicKey.type,'public');
 assert.equal(pair.privateKey.type,'private');
 assert.equal(pair.publicKey.asymmetricKeyType,'ed25519');
 assert.equal(pair.privateKey.asymmetricKeyType,'ed25519');
 assert(spki(crypto.createPublicKey(pair.privateKey)).equals(spki(pair.publicKey)),'public key derives from private key');
}
function assertSamePair(a,b){
 assert(pkcs8(a.privateKey).equals(pkcs8(b.privateKey)));
 assert(spki(a.publicKey).equals(spki(b.publicKey)));
}

// Awaits fn and requires an Error whose message leaks no private key material.
async function refuses(fn,label,secrets=[]){
 let err;
 try{await fn();}catch(e){err=e;}
 assert(err instanceof Error,`${label}: expected an Error`);
 const msg=String(err.message)+String(err.stack);
 assert(!msg.includes('PRIVATE KEY'),`${label}: error leaks PEM`);
 for(const s of secrets)assert(!msg.includes(s),`${label}: error leaks key material`);
 return err;
}

// Creates a key file with a fresh fake and generator, as on first launch.
async function firstUse(t){
 const dir=await tempDir(t);
 const filePath=keyFile(dir);
 const sto=fakeSafeStorage();
 const gen=spyGenerator();
 const pair=await load({safeStorage:sto,filePath,keyGenerator:gen});
 const bytes=await fs.readFile(filePath);
 return {dir,filePath,sto,gen,pair,bytes,envelope:JSON.parse(bytes.toString('utf8'))};
}

test('module exports loadOrCreateKeyPair',()=>{
 assert.equal(typeof store.loadOrCreateKeyPair,'function');
});

test('encryption unavailable: throws, calls neither encrypt nor keyGenerator, writes nothing',async(t)=>{
 const notConfirmed=[false,()=>undefined,null,0,1,'true',{},()=>{throw new Error('fake availability failure');}];
 for(const [i,available] of notConfirmed.entries()){
  const dir=await tempDir(t);
  const sto=fakeSafeStorage({available});
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:sto,filePath:keyFile(dir),keyGenerator:gen}),`availability #${i}`);
  assert.equal(sto.calls.encryptIn.length,0,`availability #${i}: encrypt called`);
  assert.equal(sto.calls.decryptIn.length,0,`availability #${i}: decrypt called`);
  assert.equal(gen.results.length,0,`availability #${i}: keyGenerator called`);
  assert.deepEqual(await fs.readdir(dir),[],`availability #${i}: file written`);
 }
});

test('encryption unavailable at restart: existing file is not decrypted and stays untouched',async(t)=>{
 const first=await firstUse(t);
 const sto=fakeSafeStorage({available:false});
 const gen=spyGenerator();
 await refuses(()=>load({safeStorage:sto,filePath:first.filePath,keyGenerator:gen}),'restart unavailable');
 assert.equal(sto.calls.decryptIn.length,0);
 assert.equal(sto.calls.encryptIn.length,0);
 assert.equal(gen.results.length,0);
 assert((await fs.readFile(first.filePath)).equals(first.bytes));
});

test('weak or unconfirmed Linux backend fails closed before any key work',async(t)=>{
 const weak=['basic_text','unknown','some_future_backend','',()=>undefined,()=>{throw new Error('fake backend failure');}];
 for(const [i,backend] of weak.entries()){
  const label=`backend #${i} ${typeof backend==='string'?JSON.stringify(backend):'fn'}`;
  const dir=await tempDir(t);
  const sto=fakeSafeStorage({backend});
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:sto,filePath:keyFile(dir),keyGenerator:gen,platform:'linux'}),label);
  assert.equal(sto.calls.encryptIn.length,0,`${label}: encrypt called`);
  assert.equal(gen.results.length,0,`${label}: keyGenerator called`);
  assert.deepEqual(await fs.readdir(dir),[],`${label}: file written`);
 }
 // An existing file is not decrypted under a weak backend either.
 const first=await firstUse(t);
 for(const backend of ['basic_text','unknown']){
  const sto=fakeSafeStorage({backend});
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:sto,filePath:first.filePath,keyGenerator:gen,platform:'linux'}),`restart ${backend}`);
  assert.equal(sto.calls.decryptIn.length,0,`restart ${backend}: decrypt called`);
  assert.equal(gen.results.length,0);
  assert((await fs.readFile(first.filePath)).equals(first.bytes));
 }
});

test('allowlisted Linux backends and an absent backend method are accepted',async(t)=>{
 for(const backend of ['gnome_libsecret','kwallet','kwallet5','kwallet6',undefined]){
  const dir=await tempDir(t);
  const sto=fakeSafeStorage({backend});
  const pair=await load({safeStorage:sto,filePath:keyFile(dir),keyGenerator:spyGenerator(),platform:'linux'});
  assertEd25519Pair(pair);
  if(backend!==undefined)assert(sto.calls.getSelectedStorageBackend>=1,`${backend}: backend not checked`);
 }
});

test('macOS trusts safeStorage encryption availability and does not require the Linux-only backend probe',async(t)=>{
 const dir=await tempDir(t);
 const sto=fakeSafeStorage({backend:'keychain'});
 const pair=await load({safeStorage:sto,filePath:keyFile(dir),keyGenerator:spyGenerator(),platform:'darwin'});
 assertEd25519Pair(pair);
 assert.equal(sto.calls.getSelectedStorageBackend,0);
});

test('first use: generates once and stores only the encrypted base64 envelope, mode 0600',async(t)=>{
 const {dir,filePath,sto,gen,pair,bytes,envelope}=await firstUse(t);
 assert.equal(gen.results.length,1);
 assertEd25519Pair(pair);
 assertSamePair(pair,gen.results[0]);
 assert.equal(sto.calls.encryptIn.length,1);
 assert(sto.calls.isEncryptionAvailable>=1);

 // Envelope shape: exactly three fields, ciphertext is canonical base64 of encryptString output.
 assert.deepEqual(Object.keys(envelope).sort(),['alg','ciphertext','v']);
 assert.equal(envelope.v,1);
 assert.equal(envelope.alg,'ed25519');
 assert.equal(typeof envelope.ciphertext,'string');
 const ct=Buffer.from(envelope.ciphertext,'base64');
 assert.equal(ct.toString('base64'),envelope.ciphertext,'ciphertext is canonical base64');
 assert(ct.equals(Buffer.from(sto.calls.encryptOut[0])),'ciphertext is exactly what safeStorage returned');

 // No private key material in any form on disk.
 const text=bytes.toString('utf8');
 const der=pkcs8(pair.privateKey);
 const seed=der.subarray(der.length-32);
 assert(!text.includes('PRIVATE KEY'));
 assert(!text.includes(privatePem(pair.privateKey)));
 for(const enc of ['base64','base64url','hex']){
  assert(!text.includes(der.toString(enc)),`pkcs8 ${enc} on disk`);
  assert(!text.includes(seed.toString(enc)),`seed ${enc} on disk`);
 }
 assert(!bytes.includes(der),'pkcs8 der on disk');
 assert(!bytes.includes(seed),'raw seed on disk');
 assert(!text.includes(sto.calls.encryptIn[0]),'plaintext given to encryptString is on disk');

 // Restrictive mode, and no temp file left behind.
 if(process.platform!=='win32'){
  assert.equal((await fs.stat(filePath)).mode&0o777,0o600);
 }
 assert.deepEqual(await fs.readdir(dir),[path.basename(filePath)]);
});

test('restart with the same safeStorage restores the same keypair without generating',async(t)=>{
 const first=await firstUse(t);
 const sto=fakeSafeStorage(); // fresh fake, same fixed XOR byte: a new process, same keychain
 const gen=spyGenerator();
 const pair=await load({safeStorage:sto,filePath:first.filePath,keyGenerator:gen});
 assertEd25519Pair(pair);
 assertSamePair(pair,first.pair);
 assert.equal(gen.results.length,0,'keyGenerator called on restart');
 assert.equal(sto.calls.encryptIn.length,0,'re-encrypted on restart');
 assert.equal(sto.calls.decryptIn.length,1);
 assert((await fs.readFile(first.filePath)).equals(first.bytes),'file rewritten on restart');
 // The restored private key signs for the original public key.
 const msg=Buffer.from('synthetic message');
 assert(crypto.verify(null,msg,first.pair.publicKey,crypto.sign(null,msg,pair.privateKey)));
});

test('default keyGenerator makes an Ed25519 pair that survives a restart',async(t)=>{
 const dir=await tempDir(t);
 const filePath=keyFile(dir);
 const a=await load({safeStorage:fakeSafeStorage(),filePath});
 assertEd25519Pair(a);
 const b=await load({safeStorage:fakeSafeStorage(),filePath});
 assertSamePair(a,b);
});

test('corrupt or malformed envelope fails closed and never regenerates',async(t)=>{
 const first=await firstUse(t);
 const env=first.envelope;
 const ct=Buffer.from(env.ciphertext,'base64');
 const secrets=[privatePem(first.pair.privateKey),pkcs8(first.pair.privateKey).toString('base64')];
 const cases={
  'empty file':'',
  'not json':'not json',
  'json null':'null',
  'json array':'[]',
  'empty object':'{}',
  'v 2':JSON.stringify({...env,v:2}),
  'v string':JSON.stringify({...env,v:'1'}),
  'alg x25519':JSON.stringify({...env,alg:'x25519'}),
  'ciphertext missing':JSON.stringify({v:1,alg:'ed25519'}),
  'ciphertext empty':JSON.stringify({...env,ciphertext:''}),
  'ciphertext not base64':JSON.stringify({...env,ciphertext:'!!!!'}),
  'ciphertext number':JSON.stringify({...env,ciphertext:42}),
  'ciphertext with newline':JSON.stringify({...env,ciphertext:env.ciphertext.slice(0,8)+'\n'+env.ciphertext.slice(8)}),
  'ciphertext with trailing space':JSON.stringify({...env,ciphertext:env.ciphertext+' '}),
  'ciphertext truncated':JSON.stringify({...env,ciphertext:ct.subarray(0,Math.floor(ct.length/2)).toString('base64')}),
  'ciphertext extended':JSON.stringify({...env,ciphertext:Buffer.concat([ct,Buffer.from([1,2,3])]).toString('base64')}),
  'extra field':JSON.stringify({...env,extra:'x'}),
  'decrypts to garbage':JSON.stringify({...env,ciphertext:fakeXor(Buffer.from('not a key')).toString('base64')}),
  'decrypts to empty':JSON.stringify({...env,ciphertext:fakeXor(Buffer.alloc(0)).toString('base64')}),
 };
 for(const [label,content] of Object.entries(cases)){
  await fs.writeFile(first.filePath,content);
  const before=await fs.readFile(first.filePath);
  const sto=fakeSafeStorage();
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:sto,filePath:first.filePath,keyGenerator:gen}),label,secrets);
  assert.equal(gen.results.length,0,`${label}: regenerated`);
  assert.equal(sto.calls.encryptIn.length,0,`${label}: encrypted again`);
  assert((await fs.readFile(first.filePath)).equals(before),`${label}: file changed`);
  assert.deepEqual(await fs.readdir(first.dir),[path.basename(first.filePath)],`${label}: stray file`);
 }
});

test('any single-bit flip in the ciphertext is rejected, never a different key',async(t)=>{
 const first=await firstUse(t);
 const ct=Buffer.from(first.envelope.ciphertext,'base64');
 const secrets=[privatePem(first.pair.privateKey),pkcs8(first.pair.privateKey).toString('base64')];
 for(const mask of [0x01,0x20]){
  for(let i=0;i<ct.length;i++){
   const bad=Buffer.from(ct);
   bad[i]^=mask;
   await fs.writeFile(first.filePath,JSON.stringify({...first.envelope,ciphertext:bad.toString('base64')}));
   const gen=spyGenerator();
   await refuses(()=>load({safeStorage:fakeSafeStorage(),filePath:first.filePath,keyGenerator:gen}),
    `flip byte ${i} mask ${mask}`,secrets);
   assert.equal(gen.results.length,0,`flip byte ${i} mask ${mask}: regenerated`);
  }
 }
});

test('encryptString failure or unusable output fails closed and writes nothing',async(t)=>{
 const failures={
  'throws':()=>{throw new Error('fake encrypt failure');},
  'returns string':(p)=>p,
  'returns undefined':()=>undefined,
  'returns empty buffer':()=>Buffer.alloc(0),
 };
 for(const [label,encrypt] of Object.entries(failures)){
  const dir=await tempDir(t);
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:fakeSafeStorage({encrypt}),filePath:keyFile(dir),keyGenerator:gen}),`encrypt ${label}`);
  assert.deepEqual(await fs.readdir(dir),[],`encrypt ${label}: file written`);
 }
});

test('decryptString failure or unusable output fails closed, file untouched, no regeneration',async(t)=>{
 const first=await firstUse(t);
 const failures={
  'throws':()=>{throw new Error('fake decrypt failure');},
  'returns buffer':(b)=>fakeXor(b),
  'returns undefined':()=>undefined,
  'returns empty string':()=>'',
 };
 for(const [label,decrypt] of Object.entries(failures)){
  const sto=fakeSafeStorage({decrypt});
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:sto,filePath:first.filePath,keyGenerator:gen}),`decrypt ${label}`);
  assert.equal(gen.results.length,0,`decrypt ${label}: regenerated`);
  assert.equal(sto.calls.encryptIn.length,0,`decrypt ${label}: encrypted again`);
  assert((await fs.readFile(first.filePath)).equals(first.bytes),`decrypt ${label}: file changed`);
 }
});

test('keyGenerator output that is not a matching Ed25519 pair is refused, nothing written',async(t)=>{
 const a=crypto.generateKeyPairSync('ed25519');
 const b=crypto.generateKeyPairSync('ed25519');
 const bad={
  'x25519':()=>crypto.generateKeyPairSync('x25519'),
  'ec p256':()=>crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'}),
  'mismatched pair':()=>({publicKey:a.publicKey,privateKey:b.privateKey}),
  'pem strings':()=>({publicKey:a.publicKey.export({type:'spki',format:'pem'}),privateKey:privatePem(a.privateKey)}),
  'empty object':()=>({}),
  'null':()=>null,
  'throws':()=>{throw new Error('fake generator failure');},
 };
 for(const [label,impl] of Object.entries(bad)){
  const dir=await tempDir(t);
  await refuses(()=>load({safeStorage:fakeSafeStorage(),filePath:keyFile(dir),keyGenerator:spyGenerator(impl)}),`generator ${label}`);
  assert.deepEqual(await fs.readdir(dir),[],`generator ${label}: file written`);
 }
});

// Builds a decrypted payload the way the module does, so a test can hand-craft one field.
// The digest is unkeyed SHA-256, so anyone who controls the plaintext can recompute it.
const INNER_DOMAIN_FOR_TEST='mycrm.desktop.consent-private-key.v1';
function craftedPayload(privatePemText,publicKeyB64){
 const digest=crypto.createHash('sha256').update(INNER_DOMAIN_FOR_TEST,'utf8').update('\n','utf8')
  .update(privatePemText,'utf8').update('\n','utf8').update(publicKeyB64,'ascii').digest('base64');
 return JSON.stringify({v:1,alg:'ed25519',privateKey:privatePemText,publicKey:publicKeyB64,digest});
}

test('payload with a correct digest but undecodable public key fails with the module error only',async(t)=>{
 const first=await firstUse(t);
 const pem=privatePem(first.pair.privateKey);
 const junk=Buffer.alloc(44,0x41).toString('base64'); // 44 bytes, canonical base64, not SPKI DER
 const env={v:1,alg:'ed25519',ciphertext:fakeXor(Buffer.from(craftedPayload(pem,junk),'utf8')).toString('base64')};
 await fs.writeFile(first.filePath,JSON.stringify(env));
 const before=await fs.readFile(first.filePath);
 const gen=spyGenerator();
 const err=await refuses(()=>load({safeStorage:fakeSafeStorage(),filePath:first.filePath,keyGenerator:gen}),
  'undecodable public key',[pem]);
 // A lower-level crypto error must not escape; the module throws its own message without a cause.
 assert.match(err.message,/^stored consent key/);
 assert.equal(err.cause,undefined);
 assert.equal(gen.results.length,0);
 assert((await fs.readFile(first.filePath)).equals(before));
});

test('symlinked or broadly readable key file fails closed, target untouched',{skip:process.platform==='win32'},async(t)=>{
 const first=await firstUse(t);
 // Symlink to a valid key file.
 const link=path.join(first.dir,'link.json');
 await fs.symlink(first.filePath,link);
 let gen=spyGenerator();
 await refuses(()=>load({safeStorage:fakeSafeStorage(),filePath:link,keyGenerator:gen}),'symlink');
 assert.equal(gen.results.length,0,'symlink: regenerated');
 // Dangling symlink: must not be treated as absent, and nothing is written through it.
 const dangling=path.join(first.dir,'dangling.json');
 const danglingTarget=path.join(first.dir,'nowhere.json');
 await fs.symlink(danglingTarget,dangling);
 gen=spyGenerator();
 await refuses(()=>load({safeStorage:fakeSafeStorage(),filePath:dangling,keyGenerator:gen}),'dangling symlink');
 assert.equal(gen.results.length,0,'dangling: generated');
 await assert.rejects(fs.lstat(danglingTarget),{code:'ENOENT'});
 assert((await fs.readFile(first.filePath)).equals(first.bytes));
 // Group or other permission bits on the real file.
 for(const mode of [0o640,0o604,0o644]){
  await fs.chmod(first.filePath,mode);
  gen=spyGenerator();
  const sto=fakeSafeStorage();
  await refuses(()=>load({safeStorage:sto,filePath:first.filePath,keyGenerator:gen}),`mode ${mode.toString(8)}`);
  assert.equal(sto.calls.decryptIn.length,0,`mode ${mode.toString(8)}: decrypted`);
  assert.equal(gen.results.length,0,`mode ${mode.toString(8)}: regenerated`);
  assert((await fs.readFile(first.filePath)).equals(first.bytes));
 }
});

test('stale lock fails closed and is not removed by the refused caller',async(t)=>{
 const dir=await tempDir(t);
 const filePath=keyFile(dir);
 await fs.writeFile(`${filePath}.lock`,'');
 const gen=spyGenerator();
 await refuses(()=>load({safeStorage:fakeSafeStorage(),filePath,keyGenerator:gen}),'stale lock');
 assert.equal(gen.results.length,0);
 assert.deepEqual(await fs.readdir(dir),[path.basename(filePath)+'.lock']);
});

test('concurrent first use stores one key; every success returns that key',async(t)=>{
 const dir=await tempDir(t);
 const filePath=keyFile(dir);
 const results=await Promise.allSettled(Array.from({length:4},()=>load({safeStorage:fakeSafeStorage(),filePath})));
 const ok=results.filter((r)=>r.status==='fulfilled').map((r)=>r.value);
 assert(ok.length>=1,'no caller succeeded');
 for(const r of results.filter((x)=>x.status==='rejected')){
  assert(r.reason instanceof Error);
  assert(!String(r.reason.message).includes('PRIVATE KEY'));
 }
 const stored=await load({safeStorage:fakeSafeStorage(),filePath,keyGenerator:()=>{throw new Error('must not regenerate');}});
 for(const p of ok)assertSamePair(p,stored);
 assert.deepEqual(await fs.readdir(dir),[path.basename(filePath)],'lock or temp file left behind');
});

test('missing safeStorage or filePath is refused before touching storage',async(t)=>{
 const dir=await tempDir(t);
 await refuses(()=>load({filePath:keyFile(dir)}),'no safeStorage');
 await refuses(()=>load(undefined),'no options');
 for(const filePath of [undefined,'',42]){
  const sto=fakeSafeStorage();
  const gen=spyGenerator();
  await refuses(()=>load({safeStorage:sto,filePath,keyGenerator:gen}),`filePath ${String(filePath)}`);
  assert.equal(sto.calls.encryptIn.length,0);
  assert.equal(gen.results.length,0);
 }
 assert.deepEqual(await fs.readdir(dir),[]);
});
