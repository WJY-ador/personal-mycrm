'use strict';
// desktop/scripts/mac-sign.cjs and the pure parts of desktop/scripts/check-build.cjs.
// No codesign here: these run on every installer runner, Windows included.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const sign = require('../scripts/mac-sign.cjs');
const build = require('../scripts/check-build.cjs');
const pkg = require('../package.json');

const SHA1 = '27997f35195b900a35350d3aa366154b3b4ea2f5';
const OPTS = { app: '/x/MyCRM.app', identity: '-', platform: 'darwin', optionsForFile: () => ({}) };

function recorder() {
  const calls = [];
  return { calls, signer: async opts => { calls.push(opts); } };
}

test('without the release variables the options pass through unchanged (ad-hoc)', async () => {
  const r = recorder();
  await sign.create(r.signer, {})(OPTS);
  assert.equal(r.calls.length, 1);
  assert.strictEqual(r.calls[0], OPTS);
});

test('with both release variables the release certificate signs, without Apple lookups', async () => {
  const r = recorder();
  await sign.create(r.signer, { MYCRM_MAC_SIGN_SHA1: SHA1, MYCRM_MAC_SIGN_KEYCHAIN: '/tmp/k.keychain-db' })(OPTS);
  const used = r.calls[0];
  assert.equal(used.identity, SHA1.toUpperCase());
  assert.equal(used.keychain, '/tmp/k.keychain-db');
  assert.equal(used.identityValidation, false);
  // osx-sign reads timestamp only from optionsForFile; a top-level value would be dead.
  assert.equal(used.timestamp, undefined);
  assert.equal(used.app, OPTS.app);
  assert.equal(used.optionsForFile, OPTS.optionsForFile);
});

test('one variable alone, or a malformed SHA-1, stops the build', async () => {
  const r = recorder();
  await assert.rejects(sign.create(r.signer, { MYCRM_MAC_SIGN_SHA1: SHA1 })(OPTS), /set both/);
  await assert.rejects(sign.create(r.signer, { MYCRM_MAC_SIGN_KEYCHAIN: '/tmp/k' })(OPTS), /set both/);
  await assert.rejects(sign.create(r.signer, { MYCRM_MAC_SIGN_SHA1: 'Developer ID', MYCRM_MAC_SIGN_KEYCHAIN: '/tmp/k' })(OPTS), /40-hex/);
  assert.equal(r.calls.length, 0);
});

test('electron-builder resolves the hook to the sign function itself', () => {
  // app-builder-lib resolveFunction: a named export "sign" would win over the module function.
  assert.equal(typeof sign, 'function');
  assert.equal(sign.sign, undefined);
  assert.equal(pkg.build.mac.sign, './scripts/mac-sign.cjs');
});

test('build config: update feed on GitHub, mac zip for the updater, scripts stay out of the app', () => {
  assert.deepEqual(pkg.build.publish, { provider: 'github', owner: 'WJY-ador', repo: 'personal-mycrm' });
  assert.deepEqual(pkg.build.mac.target, ['dmg', 'zip']);
  assert.equal(pkg.build.mac.identity, '-');
  assert.equal(pkg.build.mac.hardenedRuntime, true);
  assert.deepEqual(pkg.build.files, ['src/**/*', 'package.json']);
  assert.equal(pkg.build.artifactName, 'MyCRM-${version}-${os}-${arch}.${ext}');
  assert.equal(pkg.dependencies['electron-updater'], '6.8.11');
  assert.equal(pkg.mycrmMacUpdater, undefined, 'the marker is added only by the release build');
  assert.match(pkg.scripts.dist, /--publish never/);
});

test('designated requirement lines, release and ad-hoc', () => {
  const release = 'Executable=/x\ndesignated => identifier "io.mycrm.desktop" and certificate root = H"' + SHA1 + '"\n';
  const adhoc = '# designated => cdhash H"c3043a01e96fc98563731e6722f60a576cab7143"\n';
  assert.equal(build.signatureMode(build.designatedLine(release), SHA1.toUpperCase()), 'release');
  assert.equal(build.signatureMode(build.designatedLine(adhoc), ''), 'adhoc');
  assert.equal(build.signatureMode(build.designatedLine(adhoc), SHA1), 'adhoc');
  // A certificate without an organisation gives "certificate leaf"; the release check refuses it.
  const leaf = 'designated => identifier "io.mycrm.desktop" and certificate leaf = H"' + SHA1 + '"';
  assert.equal(build.signatureMode(leaf, SHA1), 'other');
  assert.equal(build.signatureMode(release.split('\n')[1], 'ffffffffffffffffffffffffffffffffffffffff'), 'other');
  assert.equal(build.designatedLine('Executable=/x\n'), null);
});

test('feed check needs the installer the feed names, and every listed file', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mycrm-build-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const put = name => fs.writeFileSync(path.join(dir, name), 'x');
  fs.writeFileSync(path.join(dir, 'latest.yml'), 'version: 0.2.0\nfiles:\n  - url: MyCRM-0.2.0-win-x64.exe\n    sha512: x\npath: MyCRM-0.2.0-win-x64.exe\n');
  assert.throws(() => build.checkFeed(dir, 'win', 'x64', '0.2.0'), /MyCRM-0\.2\.0-win-x64\.exe missing/);
  put('MyCRM-0.2.0-win-x64.exe');
  put('MyCRM-0.2.0-win-x64.exe.blockmap');
  build.checkFeed(dir, 'win', 'x64', '0.2.0');
  assert.deepEqual(build.feedFiles(fs.readFileSync(path.join(dir, 'latest.yml'), 'utf8')), ['MyCRM-0.2.0-win-x64.exe']);
  assert.throws(() => build.checkFeed(dir, 'mac', 'arm64', '0.2.0'), /latest-mac\.yml missing/);
});
