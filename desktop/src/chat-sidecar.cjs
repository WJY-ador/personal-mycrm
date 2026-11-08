'use strict';
const path=require('node:path');

const SOCKET_ENV='MYCRM_CHAT_BRIDGE_SOCKET';
const TOKEN_ENV='MYCRM_CHAT_BRIDGE_TOKEN';
const TOKEN=/^[A-Za-z0-9_-]{43}$/;

function chatSidecarSpec(env){
 if(!env||typeof env!=='object'||Array.isArray(env)||Object.getPrototypeOf(env)!==Object.prototype
   ||Object.keys(env).sort().join(',')!==[SOCKET_ENV,TOKEN_ENV].sort().join(','))throw new Error('bridge capability');
 if(typeof env[SOCKET_ENV]!=='string'||!path.isAbsolute(env[SOCKET_ENV])||env[SOCKET_ENV].includes('\0')
   ||typeof env[TOKEN_ENV]!=='string'||!TOKEN.test(env[TOKEN_ENV]))throw new Error('bridge capability');
 return Object.freeze({args:Object.freeze(['chat']),env:Object.freeze({
  [SOCKET_ENV]:env[SOCKET_ENV],[TOKEN_ENV]:env[TOKEN_ENV],
 })});
}

async function startChatSidecar(supervisor,bridge){
 if(!supervisor||typeof supervisor.start!=='function'||!bridge||typeof bridge.start!=='function')throw new TypeError('chat sidecar');
 const spec=chatSidecarSpec(await bridge.start());
 supervisor.start('chat',spec.args,{env:spec.env});
 return spec;
}

module.exports=Object.freeze({chatSidecarSpec,startChatSidecar});
