'use strict';
// After a failed mac dist, force-detach the disk images dmgbuild left attached, and nothing else.
//
//   dmg-leftovers.cjs <release/desktop>
//
// electron-builder compresses the zip while dmgbuild builds the dmg (ArchiveTarget queues its work), and on
// the macos-15-intel runner dmgbuild's last `hdiutil detach` has failed with "Resource busy". dmgbuild
// builds in a writable temp image next to the output, <output dir>/.temp<random><name>.dmg, so only
// images at that path are detached; other mounted images on the machine are left alone.
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

// Whole-disk devices (/dev/diskN) of dmgbuild temp images in outDir, from `hdiutil info -plist` as JSON.
function leftoverDevices(info, outDir) {
  const devices = [];
  for (const image of (info && info.images) || []) {
    const imagePath = image['image-path'] || '';
    if (path.dirname(imagePath) !== outDir || !/^\.temp.*\.dmg$/.test(path.basename(imagePath))) continue;
    for (const entity of image['system-entities'] || []) {
      const device = entity['dev-entry'] || '';
      if (/^\/dev\/disk\d+$/.test(device)) devices.push(device);
    }
  }
  return devices;
}

function attachedImages() {
  const plist = execFileSync('hdiutil', ['info', '-plist']);
  return JSON.parse(execFileSync('plutil', ['-convert', 'json', '-o', '-', '-'], { input: plist }).toString('utf8'));
}

function main(dir) {
  // dmgbuild names the temp image after the real path of the output folder.
  const outDir = fs.realpathSync(dir);
  const devices = leftoverDevices(attachedImages(), outDir);
  for (const device of devices) execFileSync('hdiutil', ['detach', '-force', device], { stdio: 'inherit' });
  console.log(`dmgbuild leftovers detached: ${devices.length ? devices.join(', ') : 'none'}`);
}

if (require.main === module) {
  const args = process.argv.slice(2);
  try {
    if (args.length !== 1) throw new Error('usage: dmg-leftovers.cjs <release/desktop>');
    main(args[0]);
  } catch (error) {
    console.error('::error::' + error.message);
    process.exit(1);
  }
}

module.exports = { leftoverDevices };
