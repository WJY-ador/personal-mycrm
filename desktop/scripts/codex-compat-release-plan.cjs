'use strict';
// Only reviewed, immutable commits which are ancestors of the current main are supported.
const SHA = /^[0-9a-f]{40}$/;
function makeReleasePlan(main, document, isAncestor) {
  if (!SHA.test(main || '') || !document || Array.isArray(document) ||
      Object.keys(document).join(',') !== 'supported_commits' ||
      !Array.isArray(document.supported_commits) || document.supported_commits.length > 199 ||
      typeof isAncestor !== 'function') throw new Error('invalid-release-plan');
  const result = [];
  for (const sha of [main, ...document.supported_commits]) {
    if (typeof sha !== 'string' || !SHA.test(sha) || !isAncestor(sha))
      throw new Error('invalid-release-plan');
    if (!result.includes(sha)) result.push(sha);
  }
  return result;
}
function selectReleased(releases, lookup, isAncestor) {
  // A full page may be truncated; refuse silent loss of support for older builds.
  if (!Array.isArray(releases) || releases.length >= 200) throw new Error('invalid-releases');
  const result=[];
  for (const release of releases) {
    const tag=release && release.tagName;
    if (typeof tag !== 'string' || !/^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(tag)) continue;
    const entry=lookup(tag);
    if (!entry || !SHA.test(entry.sha || '') || !isAncestor(entry.sha) || entry.version !== tag.slice(1))
      throw new Error('invalid-release');
    if (entry.supports && !result.includes(entry.sha)) result.push(entry.sha);
  }
  return result;
}
module.exports = {makeReleasePlan,selectReleased};
if (require.main === module) {
  try {
    const fs = require('node:fs');
    const {spawnSync} = require('node:child_process');
    const head = process.env.GITHUB_SHA;
    const doc = JSON.parse(fs.readFileSync('.github/codex-compat-supported.json', 'utf8'));
    const isAncestor = sha => {
      const r = spawnSync('git', ['merge-base', '--is-ancestor', sha, head], {timeout:5000,stdio:'ignore'});
      return r.status === 0;
    };
    const published = spawnSync('gh', ['release','list','--exclude-drafts','--exclude-pre-releases',
      '--limit','200','--json','tagName'], {encoding:'utf8',timeout:30000,maxBuffer:65536});
    if (published.status !== 0) throw new Error('release-list-unavailable');
    const lookup=tag => {
      const shaResult=spawnSync('git',['rev-parse','--verify',`refs/tags/${tag}^{commit}`],{encoding:'utf8',timeout:5000});
      if (shaResult.status!==0) throw new Error('invalid-release');
      const sha=shaResult.stdout.trim();
      const data=spawnSync('git',['show',`${sha}:desktop/package.json`],{encoding:'utf8',timeout:5000,maxBuffer:65536});
      if (data.status!==0) throw new Error('invalid-release');
      const present=spawnSync('git',['cat-file','-e',`${sha}:agent/chat_codex_compat.py`],{stdio:'ignore',timeout:5000});
      return {sha,version:JSON.parse(data.stdout).version,supports:present.status===0};
    };
    const released=selectReleased(JSON.parse(published.stdout),lookup,isAncestor);
    const plan = makeReleasePlan(head, {supported_commits:[...doc.supported_commits,...released]}, isAncestor);
    process.stdout.write('sources=' + JSON.stringify(plan) + '\n');
  } catch (_) {
    process.stderr.write('invalid supported compatibility releases\n');
    process.exitCode = 1;
  }
}
