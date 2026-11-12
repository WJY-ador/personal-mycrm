'use strict';
// Standing allows of this PC (J JD1, JD3). The server keeps one per (PC, AI service) through app restarts and screen
// locks (JD2). The connection window lists this installation's allows and the person releases one by hand.
// Requests use the dashboard session cookie (and Origin on the POST), never a device token: a release only takes
// permission away. Only provider names leave this module; ids and the server body stay here. No Electron here.
const PERMITS_PATH='/api/chat/permits';
const PERMIT_REVOKE_PATH='/api/chat/permits/revoke';
const PROVIDERS=Object.freeze(['claude','codex']);
const INSTALLATION=/^di_[0-9a-f]{24}$/;

// deps: request(method,url,body,headers) -> {status,body} · hosted · installationId() · usable() -> bool
//       cancel() aborts an allow window still open for this PC · log(component,event,code)
function createPermits({request,hosted,installationId,usable,cancel=()=>{},log=()=>{}}){
 const origin=new URL(hosted).origin;
 const id=()=>{const v=installationId();return typeof v==='string'&&INSTALLATION.test(v)?v:null;};
 async function state(){
  const installation=id();
  if(!usable()||!installation)return {known:false,providers:[]};
  let r;
  try{r=await request('GET',new URL(PERMITS_PATH,hosted).href,null);}catch{return {known:false,providers:[]};}
  if(!r||r.status!==200||!r.body||!Array.isArray(r.body.permits))return {known:false,providers:[]};
  const providers=PROVIDERS.filter(name=>r.body.permits.some(p=>p&&typeof p==='object'&&p.installation_id===installation&&p.provider===name));
  return {known:true,providers};
 }
 async function release(provider){
  if(!PROVIDERS.includes(provider))throw new Error('input');
  const installation=id();
  if(!usable()||!installation)throw new Error('permit-failed');
  try{cancel();}catch{}
  let r;
  try{r=await request('POST',new URL(PERMIT_REVOKE_PATH,hosted).href,{installation_id:installation,provider},
   {'Origin':origin,'Content-Type':'application/json'});}catch{r=null;}
  if(r&&r.status===401)throw new Error('login');
  if(!r||r.status!==200||!r.body||!Number.isSafeInteger(r.body.revoked)||r.body.revoked<0){
   log('consent','permit-revoke-failed',r?.status);throw new Error('permit-failed');
  }
  log('consent','permit-revoked');
  return state();
 }
 return Object.freeze({state,release});
}

module.exports=Object.freeze({createPermits,PERMITS_PATH,PERMIT_REVOKE_PATH,PROVIDERS});
