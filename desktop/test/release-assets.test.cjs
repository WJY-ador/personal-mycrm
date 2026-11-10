'use strict';
// desktop/scripts/release-assets.cjs: release names, mac feed merge, and the feed/asset invariant.
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const yaml = require('js-yaml');
const R = require('../scripts/release-assets.cjs');

const VERSION = '0.2.0';
const SHA = 'abc123';

function sha512(buf) {
  return crypto.createHash('sha512').update(buf).digest('base64');
}

function entry(name, buf) {
  return { url: name, sha512: sha512(buf), size: buf.length };
}

// The three installer artifacts as the release job downloads them, shaped like electron-builder's output.
function fakeDist(root) {
  const dist = path.join(root, 'dist');
  const write = (dir, name, text) => {
    fs.mkdirSync(dir, { recursive: true });
    const buf = Buffer.from(text);
    fs.writeFileSync(path.join(dir, name), buf);
    return buf;
  };
  for (const arch of ['arm64', 'x64']) {
    const dir = path.join(dist, `MyCRM-mac-${arch}-${SHA}`);
    const zip = write(dir, `MyCRM-${VERSION}-mac-${arch}.zip`, `zip ${arch}`);
    const dmg = write(dir, `MyCRM-${VERSION}-mac-${arch}.dmg`, `dmg ${arch}`);
    write(dir, `MyCRM-${VERSION}-mac-${arch}.zip.blockmap`, `zip blockmap ${arch}`);
    write(dir, `MyCRM-${VERSION}-mac-${arch}.dmg.blockmap`, `dmg blockmap ${arch}`);
    const zipName = `MyCRM-${VERSION}-mac-${arch}.zip`;
    write(dir, 'latest-mac.yml', yaml.dump({
      version: VERSION,
      files: [entry(zipName, zip), entry(`MyCRM-${VERSION}-mac-${arch}.dmg`, dmg)],
      path: zipName, sha512: sha512(zip), releaseDate: arch === 'arm64' ? '2026-11-10T01:00:00.000Z' : '2026-11-10T02:00:00.000Z',
    }));
    write(dir, 'builder-debug.yml', 'noise: true\n');
  }
  const win = path.join(dist, `MyCRM-win-x64-${SHA}`);
  const exeName = `MyCRM-${VERSION}-win-x64.exe`;
  const exe = write(win, exeName, 'exe');
  write(win, `${exeName}.blockmap`, 'exe blockmap');
  write(win, 'latest.yml', yaml.dump({ version: VERSION, files: [entry(exeName, exe)], path: exeName, sha512: sha512(exe), releaseDate: '2026-11-10T03:00:00.000Z' }));
  return dist;
}

function prepared(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mycrm-release-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const upload = path.join(root, 'upload');
  R.prepare(fakeDist(root), upload, VERSION, SHA);
  // packaging/checksums.py runs between prepare and check in the workflow; any content will do here.
  fs.writeFileSync(path.join(upload, 'SHA256SUMS.txt'), 'sums\n');
  return upload;
}

const readYml = (upload, name) => yaml.load(fs.readFileSync(path.join(upload, name), 'utf8'));

test('release names keep the three download names and add the update assets', () => {
  for (const name of ['MyCRM-mac-arm64.dmg', 'MyCRM-mac-x64.dmg', 'MyCRM-win-x64.exe', 'SHA256SUMS.txt']) {
    assert.ok(R.NAMES.includes(name), name);
  }
  for (const name of ['latest.yml', 'latest-mac.yml', 'MyCRM-mac-arm64.zip', 'MyCRM-mac-x64.zip',
    'MyCRM-mac-arm64.zip.blockmap', 'MyCRM-mac-x64.zip.blockmap', 'MyCRM-win-x64.exe.blockmap']) {
    assert.ok(R.NAMES.includes(name), name);
  }
  assert.equal(R.NAMES.length, 11);
  assert.equal(R.releaseName('MyCRM-0.2.0-mac-arm64.zip.blockmap', '0.2.0'), 'MyCRM-mac-arm64.zip.blockmap');
  assert.throws(() => R.releaseName('MyCRM-0.1.9-win-x64.exe', '0.2.0'), /unexpected build file name/);
  assert.throws(() => R.releaseName('MyCRM-0.2.0-../x.exe', '0.2.0'), /unexpected build file name/);
});

test('prepare writes exactly the release assets and the check passes', t => {
  const upload = prepared(t);
  assert.deepEqual(fs.readdirSync(upload).sort(), R.NAMES);
  R.check(upload, VERSION);
});

test('merged mac feed lists both architectures under release names; MacUpdater can tell them apart', t => {
  const mac = readYml(prepared(t), 'latest-mac.yml');
  const urls = mac.files.map(f => f.url).sort();
  assert.deepEqual(urls, ['MyCRM-mac-arm64.dmg', 'MyCRM-mac-arm64.zip', 'MyCRM-mac-x64.dmg', 'MyCRM-mac-x64.zip']);
  // electron-updater MacUpdater.filterFilesForArch: arm64 by "arm64" in the URL, x64 by its absence.
  assert.deepEqual(mac.files.filter(f => !f.url.includes('arm64')).map(f => f.url).sort(), ['MyCRM-mac-x64.dmg', 'MyCRM-mac-x64.zip']);
  assert.equal(mac.version, VERSION);
  assert.equal(mac.path, 'MyCRM-mac-x64.zip');
  assert.equal(mac.releaseDate, '2026-11-10T02:00:00.000Z');
});

test('windows feed points at the fixed download name', t => {
  const win = readYml(prepared(t), 'latest.yml');
  assert.deepEqual(win.files.map(f => f.url), ['MyCRM-win-x64.exe']);
  assert.equal(win.path, 'MyCRM-win-x64.exe');
});

test('check fails when an asset differs from what a feed says', t => {
  const upload = prepared(t);
  fs.appendFileSync(path.join(upload, 'MyCRM-mac-arm64.zip'), 'tampered');
  assert.throws(() => R.check(upload, VERSION), /latest-mac\.yml: sha512 of MyCRM-mac-arm64\.zip does not match/);
});

test('check fails on a missing, extra or renamed asset', t => {
  const upload = prepared(t);
  fs.renameSync(path.join(upload, 'MyCRM-win-x64.exe.blockmap'), path.join(upload, 'MyCRM-0.2.0-win-x64.exe.blockmap'));
  assert.throws(() => R.check(upload, VERSION), /release assets differ/);
});

test('check fails when a feed points at a file that is not an asset', t => {
  const upload = prepared(t);
  const feed = readYml(upload, 'latest.yml');
  feed.files[0].url = 'MyCRM-0.2.0-win-x64.exe';
  fs.writeFileSync(path.join(upload, 'latest.yml'), yaml.dump(feed));
  assert.throws(() => R.check(upload, VERSION), /points to MyCRM-0\.2\.0-win-x64\.exe, which is not a release asset/);
});

test('check fails on a top-level path/sha512 mismatch and on a version mismatch', t => {
  const upload = prepared(t);
  const feed = readYml(upload, 'latest-mac.yml');
  feed.sha512 = feed.files.find(f => f.url === 'MyCRM-mac-arm64.zip').sha512;
  fs.writeFileSync(path.join(upload, 'latest-mac.yml'), yaml.dump(feed));
  assert.throws(() => R.check(upload, VERSION), /latest-mac\.yml: sha512 of MyCRM-mac-x64\.zip does not match/);
  assert.throws(() => R.check(upload, '0.2.1'), /version 0\.2\.0 is not 0\.2\.1/);
});

test('mac feeds with different versions or a shared file do not merge', () => {
  const a = { version: '0.2.0', files: [{ url: 'MyCRM-mac-arm64.zip' }] };
  assert.throws(() => R.mergeMacFeeds(a, { version: '0.2.1', files: [{ url: 'MyCRM-mac-x64.zip' }] }), /versions differ/);
  assert.throws(() => R.mergeMacFeeds(a, { version: '0.2.0', files: [{ url: 'MyCRM-mac-arm64.zip' }] }), /both list/);
});

test('prepare refuses a non-empty upload folder and a feed of another version', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mycrm-release-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const dist = fakeDist(root);
  const upload = path.join(root, 'upload');
  fs.mkdirSync(upload);
  fs.writeFileSync(path.join(upload, 'stale.exe'), 'x');
  assert.throws(() => R.prepare(dist, upload, VERSION, SHA), /is not empty/);
  const win = path.join(dist, `MyCRM-win-x64-${SHA}`, 'latest.yml');
  fs.writeFileSync(win, fs.readFileSync(win, 'utf8').replace(`version: ${VERSION}`, 'version: 0.1.9'));
  assert.throws(() => R.prepare(dist, path.join(root, 'upload2'), VERSION, SHA), /feed version 0\.1\.9 is not 0\.2\.0/);
});
