'use strict';
// SPIKE: node-pty 1.1.0 publishes prebuilds/darwin-*/spawn-helper without the execute bit (tarball mode 644).
// Without it pty.fork fails (posix_spawn EACCES). electron-builder keeps file modes, so fixing it here carries into the app.
const fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'..','node_modules','node-pty','prebuilds');
for(const dir of ['darwin-arm64','darwin-x64']){
  const helper=path.join(root,dir,'spawn-helper');
  if(fs.existsSync(helper))fs.chmodSync(helper,0o755);
}
