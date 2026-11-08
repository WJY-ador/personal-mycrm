// Tests for consent-signature.cjs (pure Ed25519 consent signing over a fixed binding).
// Synthetic data only: every key below is generated in-process for this test and discarded.
//
// Replay: a pure signature cannot block replay. The same (claims, signature) pair verifies every
// time it is presented until expires_at. Replay prevention belongs to the server, which must
// consume the grant (keyed by nonce) in one transaction before acting on it.
//
// Run: node --test test/consent-signature.test.cjs   (from desktop/)
const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const c=require('../src/consent-signature.cjs');

const NOW=1793000000; // epoch seconds, synthetic
const CLAIMS=Object.freeze({
 user_id:'u_test_1',
 device_id:'dev_test_1',
 session_id:'sess_test_1',
 provider:'test-provider',
 model:'test-model-1.0',
 nonce:'AAAAAAAAAAAAAAAAAAAAAA', // 22 base64url chars = 128 bits
 expires_at:NOW+300,
});
const keys=()=>crypto.generateKeyPairSync('ed25519');
// Normal signing always passes an explicit clock; signConsent requires opts.nowSeconds.
const sign=(claims,key,nowSeconds=NOW)=>c.signConsent(claims,key,{nowSeconds});
const with_=(patch)=>({...CLAIMS,...patch});
const without=(name)=>{const o={...CLAIMS};delete o[name];return o;};

test('the binding is exactly these seven fields, in this order',()=>{
 assert.deepEqual([...c.FIELDS],['user_id','device_id','session_id','provider','model','nonce','expires_at']);
 assert(Object.isFrozen(c.FIELDS));
});

test('encoding: fixed domain separator, then a JSON tuple in FIELDS order',()=>{
 assert.equal(c.DOMAIN,'mycrm.consent.v1');
 const expected='mycrm.consent.v1\n'+
  '["u_test_1","dev_test_1","sess_test_1","test-provider","test-model-1.0","AAAAAAAAAAAAAAAAAAAAAA",1793000300]';
 const bytes=c.encodeConsent(CLAIMS);
 assert(Buffer.isBuffer(bytes));
 assert.equal(bytes.toString('utf8'),expected);
});

test('encoding is deterministic and ignores object key order',()=>{
 const reversed=Object.fromEntries(Object.entries(CLAIMS).reverse());
 assert(c.encodeConsent(reversed).equals(c.encodeConsent(CLAIMS)));
 assert(c.encodeConsent({...CLAIMS}).equals(c.encodeConsent(CLAIMS)));
});

test('sign then verify round-trips; signature is unpadded base64url of 64 bytes',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 assert.match(sig,/^[A-Za-z0-9_-]{86}$/);
 assert.equal(Buffer.from(sig,'base64url').length,64);
 assert.deepEqual(c.verifyConsent(CLAIMS,sig,publicKey,{nowSeconds:NOW}),{ok:true});
});

test('slash and plus model identifiers round-trip with the shared ASCII contract',()=>{
 const {publicKey,privateKey}=keys();
 const claims=with_({model:'claude/opus+latest'});
 const bytes=c.encodeConsent(claims);
 assert.equal(bytes.toString('utf8'),
  'mycrm.consent.v1\n["u_test_1","dev_test_1","sess_test_1","test-provider","claude/opus+latest","AAAAAAAAAAAAAAAAAAAAAA",1793000300]');
 const sig=sign(claims,privateKey);
 assert.deepEqual(c.verifyConsent(claims,sig,publicKey,{nowSeconds:NOW}),{ok:true});
 assert.throws(()=>c.encodeConsent(with_({model:'claude/opus+latest\n'})),TypeError);
});

test('signature is plain Ed25519 over encodeConsent bytes (crypto.sign(null, ...))',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 assert(crypto.verify(null,c.encodeConsent(CLAIMS),publicKey,Buffer.from(sig,'base64url')));
 // Ed25519 is deterministic: the same key and bytes give the same signature.
 assert.equal(sign(CLAIMS,privateKey),sig);
});

test('domain separator is load-bearing: a signature over the bare tuple does not verify',()=>{
 const {publicKey,privateKey}=keys();
 const bare=c.encodeConsent(CLAIMS).subarray(Buffer.byteLength(c.DOMAIN+'\n'));
 const sig=crypto.sign(null,bare,privateKey).toString('base64url');
 assert.deepEqual(c.verifyConsent(CLAIMS,sig,publicKey,{nowSeconds:NOW}),{ok:false,code:'BAD-SIGNATURE'});
});

test('a different Ed25519 key is rejected',()=>{
 const a=keys(),b=keys();
 const sig=sign(CLAIMS,a.privateKey);
 assert.deepEqual(c.verifyConsent(CLAIMS,sig,b.publicKey,{nowSeconds:NOW}),{ok:false,code:'BAD-SIGNATURE'});
});

test('changing any bound field breaks the signature',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 const changed={
  user_id:'u_test_2',device_id:'dev_test_2',session_id:'sess_test_2',provider:'other-provider',
  model:'test-model-2.0',nonce:'BAAAAAAAAAAAAAAAAAAAAA',expires_at:NOW+301,
 };
 assert.deepEqual(Object.keys(changed),[...c.FIELDS]);
 for(const [k,v] of Object.entries(changed)){
  assert.deepEqual(c.verifyConsent(with_({[k]:v}),sig,publicKey,{nowSeconds:NOW}),{ok:false,code:'BAD-SIGNATURE'},k);
 }
});

test('a tampered signature is rejected',()=>{
 const {publicKey,privateKey}=keys();
 const raw=Buffer.from(sign(CLAIMS,privateKey),'base64url');
 raw[10]^=1;
 assert.deepEqual(c.verifyConsent(CLAIMS,raw.toString('base64url'),publicKey,{nowSeconds:NOW}),{ok:false,code:'BAD-SIGNATURE'});
});

test('expiry: valid strictly before expires_at, rejected at and after it',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 const at=(n)=>c.verifyConsent(CLAIMS,sig,publicKey,{nowSeconds:n});
 assert.deepEqual(at(CLAIMS.expires_at-1),{ok:true});
 assert.deepEqual(at(CLAIMS.expires_at),{ok:false,code:'EXPIRED'});
 assert.deepEqual(at(CLAIMS.expires_at+3600),{ok:false,code:'EXPIRED'});
});

test('malformed claims are rejected by verify and refused by sign',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 const bad=[
  null,undefined,'claims',42,[],[...Object.values(CLAIMS)],
  ...c.FIELDS.map(without),
  with_({extra:'x'}),
  // ids
  with_({user_id:''}),with_({user_id:'a b'}),with_({user_id:'x'.repeat(129)}),with_({user_id:7}),
  with_({user_id:'uü'}),with_({device_id:'dev\n1'}),with_({session_id:null}),
  // provider and model
  with_({provider:''}),with_({provider:'Test-Provider'}),with_({provider:'p'.repeat(33)}),
  with_({model:''}),with_({model:'a b'}),with_({model:'m'.repeat(129)}),with_({model:'claude/opus+latest\n'}),
  // nonce: base64url, 22..128 chars (at least 128 bits)
  with_({nonce:'abc'}),with_({nonce:'A'.repeat(21)}),with_({nonce:'A'.repeat(129)}),
  with_({nonce:'AAAAAAAAAAAAAAAAAAAAAA=='}),with_({nonce:'AAAAAAAAAAAAAAAAAAAA+/'}),
  // expires_at: positive safe integer, epoch seconds
  with_({expires_at:String(NOW+300)}),with_({expires_at:NOW+0.5}),with_({expires_at:0}),
  with_({expires_at:-1}),with_({expires_at:NaN}),with_({expires_at:Infinity}),
  with_({expires_at:Number.MAX_SAFE_INTEGER+1}),
 ];
 for(const b of bad){
  const label=JSON.stringify(b)??String(b);
  assert.deepEqual(c.verifyConsent(b,sig,publicKey,{nowSeconds:NOW}),{ok:false,code:'MALFORMED'},label);
  assert.throws(()=>sign(b,privateKey),TypeError,label);
  assert.throws(()=>c.encodeConsent(b),TypeError,label);
 }
});

test('malformed signatures are rejected, including non-canonical base64url',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 const A='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
 // The last of 86 chars carries 2 signature bits and 4 padding bits; flipping a padding bit
 // decodes to the same 64 bytes, so a lenient decoder would accept two strings for one signature.
 const alias=sig.slice(0,85)+A[A.indexOf(sig[85])^1];
 assert(Buffer.from(alias,'base64url').equals(Buffer.from(sig,'base64url')));
 const bad=[
  '',sig.slice(0,85),sig+'A',sig+'==',sig.replace(/^./,'+'),'!'.repeat(86),alias,
  Buffer.from(sig,'base64url'),null,undefined,42,
 ];
 for(const s of bad){
  assert.deepEqual(c.verifyConsent(CLAIMS,s,publicKey,{nowSeconds:NOW}),{ok:false,code:'MALFORMED'},String(s));
 }
});

test('keys: only Ed25519 KeyObjects are accepted, otherwise TypeError',()=>{
 const ed=keys();
 const x=crypto.generateKeyPairSync('x25519');
 const ec=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'});
 const sig=sign(CLAIMS,ed.privateKey);
 for(const k of [x.privateKey,ec.privateKey,ed.publicKey,'not a key',null]){
  assert.throws(()=>sign(CLAIMS,k),TypeError);
 }
 for(const k of [x.publicKey,ec.publicKey,ed.privateKey,'not a key',null]){
  assert.throws(()=>c.verifyConsent(CLAIMS,sig,k,{nowSeconds:NOW}),TypeError);
 }
});

test('verify needs an explicit clock in epoch seconds; the module never reads Date.now()',()=>{
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 for(const opts of [undefined,{},{nowSeconds:'1793000000'},{nowSeconds:NOW+0.5},{nowSeconds:NaN},{nowSeconds:-1}]){
  assert.throws(()=>c.verifyConsent(CLAIMS,sig,publicKey,opts),TypeError,JSON.stringify(opts));
 }
 const realNow=Date.now;
 Date.now=()=>{throw new Error('Date.now must not be called');};
 try{assert.deepEqual(c.verifyConsent(CLAIMS,sig,publicKey,{nowSeconds:NOW}),{ok:true});}
 finally{Date.now=realNow;}
});

test('sign needs an explicit clock in epoch seconds; missing or malformed clock throws TypeError',()=>{
 const {privateKey}=keys();
 const bad=[
  undefined,null,NOW,'1793000000',{},{nowSeconds:undefined},{nowSeconds:null},
  {nowSeconds:'1793000000'},{nowSeconds:NOW+0.5},{nowSeconds:NaN},{nowSeconds:Infinity},
  {nowSeconds:-1},{nowSeconds:Number.MAX_SAFE_INTEGER+1},{nowSeconds:BigInt(NOW)},
 ];
 bad.forEach((opts,i)=>{
  assert.throws(()=>c.signConsent(CLAIMS,privateKey,opts),TypeError,`bad signing clock #${i}`);
 });
 // Zero is a valid non-negative clock.
 assert.match(c.signConsent(CLAIMS,privateKey,{nowSeconds:0}),/^[A-Za-z0-9_-]{86}$/);
 const realNow=Date.now;
 Date.now=()=>{throw new Error('Date.now must not be called');};
 try{assert.match(sign(CLAIMS,privateKey),/^[A-Za-z0-9_-]{86}$/);}
 finally{Date.now=realNow;}
});

test('sign refuses claims already expired at the signing clock, at and after expires_at',()=>{
 const {publicKey,privateKey}=keys();
 const at=(n)=>()=>sign(CLAIMS,privateKey,n);
 assert.throws(at(CLAIMS.expires_at),RangeError);
 assert.throws(at(CLAIMS.expires_at+1),RangeError);
 assert.throws(at(CLAIMS.expires_at+3600),RangeError);
 const sig=at(CLAIMS.expires_at-1)();
 assert.deepEqual(c.verifyConsent(CLAIMS,sig,publicKey,{nowSeconds:CLAIMS.expires_at-1}),{ok:true});
 // The signing clock is not part of the signed bytes.
 assert.equal(sig,sign(CLAIMS,privateKey));
});

test('REPLAY IS NOT BLOCKED HERE: the same signature verifies again and again until expiry',()=>{
 // This is a documented limitation, not a bug. verifyConsent is stateless and pure.
 // Replay prevention is the server's job: it must consume the grant for this nonce in one
 // transaction (mark used and act, or roll back) and refuse any second consume.
 const {publicKey,privateKey}=keys();
 const sig=sign(CLAIMS,privateKey);
 for(let i=0;i<3;i++){
  assert.deepEqual(c.verifyConsent(CLAIMS,sig,publicKey,{nowSeconds:NOW+i}),{ok:true});
 }
 assert.equal(typeof c.consume,'undefined','no replay state lives in this module');
});

test('inputs are not mutated',()=>{
 const {privateKey,publicKey}=keys();
 const claims={...CLAIMS};
 const snapshot=JSON.stringify(claims);
 const sig=sign(claims,privateKey);
 c.verifyConsent(claims,sig,publicKey,{nowSeconds:NOW});
 assert.equal(JSON.stringify(claims),snapshot);
});
