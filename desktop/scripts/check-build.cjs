'use strict';
// Post-build checks for one installer job (.github/workflows/desktop-release.yml).
//
//   check-build.cjs <release/desktop> <mac|win> <arch> <version>
//
// Both: the update feed and the installers it names exist, and the unpacked app carries
// resources/app-update.yml (without it the app's first update check throws).
// mac only: the signing mode is one of two, never mixed.
//   release (MYCRM_MAC_SIGN_SHA1 set): the app and every Mach-O file under Resources/agent carry the
//     designated requirement `certificate root = H"<sha1>"`, and the packaged package.json has
//     mycrmMacUpdater === true (boolean).
//   ad-hoc (not set): the app is ad-hoc signed and the packaged package.json has no mycrmMacUpdater.
// A mycrmMacUpdater build that is not release-signed would break every later update, so this fails closed.
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function fail(message) {
  throw new Error(message);
}

function feedFiles(text) {
  return [...text.matchAll(/^\s*-\s*url:\s*(\S+)\s*$/gm)].map(m => m[1]);
}

function checkFeed(dir, platform, arch, version) {
  const feedName = platform === 'mac' ? 'latest-mac.yml' : 'latest.yml';
  const feed = path.join(dir, feedName);
  if (!fs.existsSync(feed)) fail(`${feedName} missing`);
  const want = platform === 'mac'
    ? [`MyCRM-${version}-mac-${arch}.zip`, `MyCRM-${version}-mac-${arch}.zip.blockmap`]
    : [`MyCRM-${version}-win-${arch}.exe`, `MyCRM-${version}-win-${arch}.exe.blockmap`];
  for (const name of want) if (!fs.existsSync(path.join(dir, name))) fail(`${name} missing`);
  const urls = feedFiles(fs.readFileSync(feed, 'utf8'));
  if (!urls.includes(want[0])) fail(`${feedName} does not list ${want[0]}`);
  for (const url of urls) if (!fs.existsSync(path.join(dir, url))) fail(`${feedName} lists ${url}, which was not built`);
}

function unpackedResources(dir, platform) {
  const pattern = platform === 'mac' ? /^mac/ : /^win/;
  const roots = fs.readdirSync(dir).filter(name => pattern.test(name) && fs.statSync(path.join(dir, name)).isDirectory());
  if (roots.length !== 1) fail(`expected one unpacked ${platform} app, found ${roots.length}`);
  return platform === 'mac'
    ? path.join(dir, roots[0], 'MyCRM.app', 'Contents', 'Resources')
    : path.join(dir, roots[0], 'resources');
}

// Designated requirement line of `codesign -d -r-`. An ad-hoc signature has only the implicit one,
// printed as a comment: `# designated => cdhash H"..."`.
function designatedLine(out) {
  return out.split('\n').map(l => l.trim()).find(l => /^(# )?designated =>/.test(l)) || null;
}

function requirement(file) {
  const out = execFileSync('codesign', ['-d', '-r-', file], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const line = designatedLine(out);
  if (!line) fail(`no designated requirement for ${path.basename(file)}`);
  return line;
}

function signatureMode(designated, sha1) {
  if (sha1 && designated.includes(`certificate root = H"${sha1.toLowerCase()}"`)) return 'release';
  if (/\bcdhash H"[0-9a-f]+"/.test(designated) && !designated.includes('certificate')) return 'adhoc';
  return 'other';
}

function isMachO(file) {
  const fd = fs.openSync(file, 'r');
  try {
    const head = Buffer.alloc(4);
    if (fs.readSync(fd, head, 0, 4, 0) < 4) return false;
    return ['feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'feedface', 'cefaedfe'].includes(head.toString('hex'));
  } finally {
    fs.closeSync(fd);
  }
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isSymbolicLink()) return [];
    return entry.isDirectory() ? walk(full) : [full];
  });
}

function packagedMetadata(resources) {
  // Read package.json out of app.asar with the asar module electron-builder ships with (pinned by the lockfile).
  const asar = require('@electron/asar');
  return JSON.parse(asar.extractFile(path.join(resources, 'app.asar'), 'package.json').toString('utf8'));
}

function checkMacSigning(resources, sha1) {
  const app = path.resolve(resources, '..', '..');
  const expected = sha1 ? 'release' : 'adhoc';
  const appMode = signatureMode(requirement(app), sha1);
  if (appMode !== expected) fail(`app signature is ${appMode}, expected ${expected}`);
  const machO = walk(path.join(resources, 'agent')).filter(isMachO);
  if (!machO.length) fail('no Mach-O files under Resources/agent');
  for (const file of machO) {
    const mode = signatureMode(requirement(file), sha1);
    if (mode !== expected) fail(`sidecar ${path.relative(resources, file)} signature is ${mode}, expected ${expected}`);
  }
  const marker = packagedMetadata(resources).mycrmMacUpdater;
  if (sha1 ? marker !== true : marker !== undefined) {
    fail(`packaged mycrmMacUpdater is ${JSON.stringify(marker)} (${typeof marker}) for a ${expected} build`);
  }
  return { mode: expected, sidecarFiles: machO.length, marker };
}

function checkBuild(dir, platform, arch, version, env) {
  if (!['mac', 'win'].includes(platform)) fail(`unknown platform ${platform}`);
  checkFeed(dir, platform, arch, version);
  const resources = unpackedResources(dir, platform);
  if (!fs.existsSync(path.join(resources, 'app-update.yml'))) fail('resources/app-update.yml missing from the unpacked app');
  if (platform !== 'mac') return { platform };
  return { platform, ...checkMacSigning(resources, env.MYCRM_MAC_SIGN_SHA1 || '') };
}

if (require.main === module) {
  const args = process.argv.slice(2);
  try {
    if (args.length !== 4) fail('usage: check-build.cjs <release/desktop> <mac|win> <arch> <version>');
    console.log('build checked: ' + JSON.stringify(checkBuild(...args, process.env)));
  } catch (error) {
    console.error('::error::' + error.message);
    process.exit(1);
  }
}

module.exports = { feedFiles, designatedLine, signatureMode, checkFeed, checkBuild };
