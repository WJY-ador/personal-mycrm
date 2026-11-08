// Pure Ed25519 consent signing over a fixed seven-field binding.
//
// Scope: encode, sign, verify. Nothing else.
// - Keys are supplied by the caller as Ed25519 KeyObjects. This module never creates, stores,
//   persists, registers, or transmits keys.
// - No I/O, no network, no provider/agent/server registration, no global state.
// - The clock is supplied by the caller (integer epoch seconds) and is required by both sign
//   and verify. Date.now() is never read.
//
// Replay: this module is stateless and does NOT prevent replay. The same (claims, signature)
// pair verifies every time until expires_at. The server must consume the grant for its nonce
// exactly once, in one transaction, before acting on it.
'use strict';
const crypto=require('node:crypto');

const DOMAIN='mycrm.consent.v1';
const FIELDS=Object.freeze(['user_id','device_id','session_id','provider','model','nonce','expires_at']);

const ID_RE=/^[A-Za-z0-9._:-]{1,128}$/;
const PROVIDER_RE=/^[a-z0-9][a-z0-9._-]{0,31}$/;
const MODEL_RE=/^[A-Za-z0-9._:/+-]{1,128}$/;
const NONCE_RE=/^[A-Za-z0-9_-]{22,128}$/;
const SIG_RE=/^[A-Za-z0-9_-]{86}$/;

const CHECKS=Object.freeze({
 user_id:(v)=>typeof v==='string'&&ID_RE.test(v),
 device_id:(v)=>typeof v==='string'&&ID_RE.test(v),
 session_id:(v)=>typeof v==='string'&&ID_RE.test(v),
 provider:(v)=>typeof v==='string'&&PROVIDER_RE.test(v),
 model:(v)=>typeof v==='string'&&MODEL_RE.test(v)&&MODEL_RE.exec(v)[0]===v,
 nonce:(v)=>typeof v==='string'&&NONCE_RE.test(v),
 expires_at:(v)=>Number.isSafeInteger(v)&&v>0,
});

// Returns a frozen tuple of values in FIELDS order, or null if claims are malformed.
// Reads each value exactly once from an own data property, so getters and later mutation
// cannot change what gets signed or verified.
function snapshot(claims){
 if(claims===null||typeof claims!=='object'||Array.isArray(claims))return null;
 const proto=Object.getPrototypeOf(claims);
 if(proto!==Object.prototype&&proto!==null)return null;
 const own=Reflect.ownKeys(claims);
 if(own.length!==FIELDS.length)return null;
 const tuple=[];
 for(const name of FIELDS){
  const d=Object.getOwnPropertyDescriptor(claims,name);
  if(!d||!('value' in d))return null;
  if(!CHECKS[name](d.value))return null;
  tuple.push(d.value);
 }
 return Object.freeze(tuple);
}

function bytesOf(tuple){
 return Buffer.from(DOMAIN+'\n'+JSON.stringify(tuple),'utf8');
}

function encodeConsent(claims){
 const tuple=snapshot(claims);
 if(!tuple)throw new TypeError('consent claims are malformed');
 return bytesOf(tuple);
}

function assertEd25519(key,type){
 if(!(key instanceof crypto.KeyObject)||key.type!==type||key.asymmetricKeyType!=='ed25519'){
  throw new TypeError(`expected an Ed25519 ${type} KeyObject`);
 }
}

function readNow(opts){
 if(opts===null||typeof opts!=='object')throw new TypeError('options object with nowSeconds is required');
 const n=opts.nowSeconds;
 if(!Number.isSafeInteger(n)||n<0)throw new TypeError('nowSeconds must be a non-negative integer in epoch seconds');
 return n;
}

// Signs the encoded claims. opts.nowSeconds is required; claims with expires_at <= nowSeconds
// are refused with RangeError. Programmer errors (wrong key type, missing clock, malformed
// claims) throw TypeError.
function signConsent(claims,privateKey,opts){
 assertEd25519(privateKey,'private');
 const now=readNow(opts);
 const tuple=snapshot(claims);
 if(!tuple)throw new TypeError('consent claims are malformed');
 if(!(tuple[6]>now))throw new RangeError('consent claims are already expired');
 return crypto.sign(null,bytesOf(tuple),privateKey).toString('base64url');
}

// Strict canonical unpadded base64url of exactly 64 bytes, or null.
function decodeSignature(sig){
 if(typeof sig!=='string'||!SIG_RE.test(sig))return null;
 const raw=Buffer.from(sig,'base64url');
 if(raw.length!==64)return null;
 if(raw.toString('base64url')!==sig)return null; // rejects non-zero padding bits (aliases)
 return raw;
}

// Returns {ok:true} or {ok:false,code} with code in MALFORMED, BAD-SIGNATURE, EXPIRED.
// Programmer errors (wrong key type, missing clock) throw TypeError.
function verifyConsent(claims,signature,publicKey,opts){
 assertEd25519(publicKey,'public');
 const now=readNow(opts);
 const tuple=snapshot(claims);
 if(!tuple)return {ok:false,code:'MALFORMED'};
 const raw=decodeSignature(signature);
 if(!raw)return {ok:false,code:'MALFORMED'};
 let valid=false;
 try{valid=crypto.verify(null,bytesOf(tuple),publicKey,raw)===true;}
 catch{valid=false;}
 if(!valid)return {ok:false,code:'BAD-SIGNATURE'};
 if(!(tuple[6]>now))return {ok:false,code:'EXPIRED'};
 return {ok:true};
}

module.exports=Object.freeze({DOMAIN,FIELDS,encodeConsent,signConsent,verifyConsent});
