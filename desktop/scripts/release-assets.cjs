'use strict';
// Release assets for the tag run's release job (.github/workflows/desktop-release.yml).
//
//   prepare <dist> <upload> <version> <sha>   copy installer artifacts to <upload> under release names,
//                                               merge the two mac update feeds into one latest-mac.yml
//   check <upload> <version>                  the asset set is exactly NAMES, and every file the feeds
//                                               point to is an asset with the same name, sha512 and size
//   names                                     print the release asset names, one per line
//
// One naming rule: a release name is the build name without "-<version>" (MyCRM-0.2.0-mac-arm64.dmg
// becomes MyCRM-mac-arm64.dmg). The three download names /download links to come out unchanged, and the
// update feeds are rewritten with the same rule, so no file is uploaded twice. Old blockmaps are still
// found: electron-updater swaps the version inside the URL path, and the GitHub path carries the tag.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
// js-yaml comes with electron-updater (a dependency of this package); it is the parser the app uses.
const yaml = require('js-yaml');

const TARGETS = [
  { platform: 'mac', arch: 'arm64', files: ['dmg', 'zip', 'zip.blockmap'], feed: 'latest-mac.yml' },
  { platform: 'mac', arch: 'x64', files: ['dmg', 'zip', 'zip.blockmap'], feed: 'latest-mac.yml' },
  { platform: 'win', arch: 'x64', files: ['exe', 'exe.blockmap'], feed: 'latest.yml' },
];
const FEEDS = ['latest-mac.yml', 'latest.yml'];
const NAMES = [
  ...TARGETS.flatMap(t => t.files.map(ext => `MyCRM-${t.platform}-${t.arch}.${ext}`)),
  ...FEEDS,
  'SHA256SUMS.txt',
].sort();
const VERSION = /^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/;

function releaseName(buildName, version) {
  const prefix = `MyCRM-${version}-`;
  if (!buildName.startsWith(prefix) || buildName.includes('/') || buildName.includes('\\')) {
    throw new Error(`unexpected build file name ${JSON.stringify(buildName)} for version ${version}`);
  }
  return 'MyCRM-' + buildName.slice(prefix.length);
}

function readFeed(file) {
  const feed = yaml.load(fs.readFileSync(file, 'utf8'));
  if (!feed || typeof feed !== 'object' || !Array.isArray(feed.files) || !feed.files.length) {
    throw new Error(`${path.basename(file)}: no files list`);
  }
  return feed;
}

function renameFeed(feed, version) {
  if (feed.version !== version) throw new Error(`feed version ${feed.version} is not ${version}`);
  const out = { ...feed, files: feed.files.map(f => ({ ...f, url: releaseName(f.url, version) })) };
  if (feed.path !== undefined) out.path = releaseName(feed.path, version);
  return out;
}

// Two single-arch mac feeds become one. MacUpdater picks the arm64 entry by "arm64" in the URL and the
// x64 one by its absence. The legacy top-level path/sha512 point at the x64 zip, which also runs on arm64.
function mergeMacFeeds(arm64, x64) {
  if (arm64.version !== x64.version) throw new Error(`mac feed versions differ: ${arm64.version} / ${x64.version}`);
  const urls = new Set();
  const files = [...arm64.files, ...x64.files].filter(f => {
    if (urls.has(f.url)) throw new Error(`mac feeds both list ${f.url}`);
    urls.add(f.url);
    return true;
  });
  const zip = x64.files.find(f => f.url.endsWith('.zip'));
  if (!zip) throw new Error('x64 mac feed has no zip');
  const releaseDate = [arm64.releaseDate, x64.releaseDate].filter(Boolean).sort().pop();
  return { version: x64.version, files, path: zip.url, sha512: zip.sha512, ...(releaseDate ? { releaseDate } : {}) };
}

function writeFeed(file, feed) {
  fs.writeFileSync(file, yaml.dump(feed, { lineWidth: -1 }), 'utf8');
}

function prepare(dist, upload, version, sha) {
  if (!VERSION.test(version)) throw new Error(`invalid version ${version}`);
  fs.mkdirSync(upload, { recursive: true });
  if (fs.readdirSync(upload).length) throw new Error(`${upload} is not empty`);
  const feeds = {};
  for (const t of TARGETS) {
    const dir = path.join(dist, `MyCRM-${t.platform}-${t.arch}-${sha}`);
    for (const ext of t.files) {
      const buildName = `MyCRM-${version}-${t.platform}-${t.arch}.${ext}`;
      fs.copyFileSync(path.join(dir, buildName), path.join(upload, releaseName(buildName, version)));
    }
    feeds[`${t.platform}-${t.arch}`] = renameFeed(readFeed(path.join(dir, t.feed)), version);
  }
  writeFeed(path.join(upload, 'latest-mac.yml'), mergeMacFeeds(feeds['mac-arm64'], feeds['mac-x64']));
  writeFeed(path.join(upload, 'latest.yml'), feeds['win-x64']);
}

function sha512(file) {
  return crypto.createHash('sha512').update(fs.readFileSync(file)).digest('base64');
}

function checkEntry(upload, feedName, url, expectedSha512, expectedSize) {
  if (!NAMES.includes(url)) throw new Error(`${feedName} points to ${url}, which is not a release asset`);
  const file = path.join(upload, url);
  if (sha512(file) !== expectedSha512) throw new Error(`${feedName}: sha512 of ${url} does not match`);
  if (expectedSize !== undefined && fs.statSync(file).size !== expectedSize) throw new Error(`${feedName}: size of ${url} does not match`);
}

function check(upload, version) {
  const actual = fs.readdirSync(upload).sort();
  if (JSON.stringify(actual) !== JSON.stringify(NAMES)) {
    throw new Error(`release assets differ.\nexpected: ${NAMES.join(', ')}\nactual:   ${actual.join(', ')}`);
  }
  for (const feedName of FEEDS) {
    const feed = readFeed(path.join(upload, feedName));
    if (feed.version !== version) throw new Error(`${feedName}: version ${feed.version} is not ${version}`);
    for (const f of feed.files) checkEntry(upload, feedName, f.url, f.sha512, f.size);
    if (!feed.path || !feed.sha512) throw new Error(`${feedName}: missing top-level path/sha512`);
    checkEntry(upload, feedName, feed.path, feed.sha512);
  }
  const mac = readFeed(path.join(upload, 'latest-mac.yml')).files.map(f => f.url);
  const win = readFeed(path.join(upload, 'latest.yml')).files.map(f => f.url);
  for (const want of ['MyCRM-mac-arm64.zip', 'MyCRM-mac-x64.zip']) {
    if (!mac.includes(want)) throw new Error(`latest-mac.yml has no ${want}`);
  }
  if (!win.includes('MyCRM-win-x64.exe')) throw new Error('latest.yml has no MyCRM-win-x64.exe');
}

function main(argv) {
  const [command, ...args] = argv;
  if (command === 'prepare' && args.length === 4) return prepare(...args);
  if (command === 'check' && args.length === 2) return check(...args);
  if (command === 'names' && args.length === 0) return process.stdout.write(NAMES.join('\n') + '\n');
  throw new Error('usage: release-assets.cjs prepare <dist> <upload> <version> <sha> | check <upload> <version> | names');
}

if (require.main === module) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error('::error::' + error.message);
    process.exit(1);
  }
}

module.exports = { NAMES, releaseName, renameFeed, mergeMacFeeds, prepare, check };
