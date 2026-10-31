'use strict';
// Pure helpers for sidecar results, kept out of main.cjs so they can be tested without Electron.
const OUTPUT_LIMIT=8192, LINE_LIMIT=300;
const LIVE=new Set(['starting','running','retry-wait']);
class OutputTail {
  // Keeps only the last bytes; decoding happens once so multi-byte Korean text is not split per chunk.
  constructor(limit=OUTPUT_LIMIT){this.limit=limit;this.chunks=[];this.size=0;}
  push(chunk){
    const b=Buffer.isBuffer(chunk)?chunk:Buffer.from(String(chunk));
    this.chunks.push(b);this.size+=b.length;
    if(this.size>this.limit*2){const kept=Buffer.concat(this.chunks).subarray(-this.limit);this.chunks=[kept];this.size=kept.length;}
  }
  text(){return Buffer.concat(this.chunks).subarray(-this.limit).toString('utf8');}
}
// Sidecar output is contractually free of tokens, keys, source text and URLs. Shown on screen only, never logged.
function failureLine(code,text) {
  if(code===0)return null;
  const lines=String(text||'').split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
  if(!lines.length)return null;
  return Array.from(lines[lines.length-1]).slice(0,LINE_LIMIT).join('');
}
function hasLiveProcess(processes){return Object.values(processes||{}).some(p=>LIVE.has(p?.state));}
module.exports={OutputTail,failureLine,hasLiveProcess,OUTPUT_LIMIT,LINE_LIMIT};
