'use strict';
// Issuance helper. Private keys are supplied by the caller and are never logged.
const crypto = require('node:crypto');
const {verifyPolicy} = require('../src/codex-compat-policy.cjs');
const PROBES = ['find','read','write','decide','fileprobe','filecat','view','shell','patch','web','mcp','goal','node','resume','revoke'];

function checkEvidence(payload, receipts, sourceSha) {
  if (!payload || payload.os !== 'darwin' || !['arm64','x64'].includes(payload.arch)
      || !Array.isArray(payload.versions)
      || !Array.isArray(receipts) || receipts.length !== payload.versions.length
      || !/^[0-9a-f]{40}$/.test(sourceSha) || payload.source_sha !== sourceSha
      || !/^[0-9a-f]{64}$/.test(payload.config_sha256 || '')) throw new Error('invalid-evidence');
  const versions = new Set();
  for (const receipt of receipts) {
    if (!receipt || Object.keys(receipt).sort().join(',') !==
      ['source_sha','version','os','arch','package_sha256','node_sha256','native_sha256','host_sha256','archive_sha256','config_sha256','probes'].sort().join(',')
      || receipt.source_sha !== sourceSha || receipt.os !== payload.os
      || (receipt.arch === 'x86_64' ? 'x64' : receipt.arch) !== payload.arch
      || !/^[0-9a-f]{64}$/.test(receipt.package_sha256 || '')
      || !/^[0-9a-f]{64}$/.test(receipt.node_sha256 || '')
      || !/^[0-9a-f]{64}$/.test(receipt.native_sha256 || '')
      || !/^[0-9a-f]{64}$/.test(receipt.host_sha256 || '')
      || !/^[0-9a-f]{64}$/.test(receipt.archive_sha256 || '')
      || receipt.config_sha256 !== payload.config_sha256
      || !Array.isArray(receipt.probes) || JSON.stringify(receipt.probes) !== JSON.stringify(PROBES)
      || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(receipt.version || '')
      || versions.has(receipt.version)) throw new Error('invalid-evidence');
    const entry = payload.versions.find(v => v && v.version === receipt.version);
    if (!entry || Object.keys(entry).sort().join(',') !== 'host_sha256,native_sha256,version'
        || entry.native_sha256 !== receipt.native_sha256 || entry.host_sha256 !== receipt.host_sha256) throw new Error('invalid-evidence');
    versions.add(receipt.version);
  }
  if (payload.versions.some(v => !v || !versions.has(v.version)))
    throw new Error('invalid-evidence');
}

function issuePolicy(payload, {privateKey, keyId, now}) {
  if (!(privateKey instanceof crypto.KeyObject) || privateKey.type !== 'private' ||
      privateKey.asymmetricKeyType !== 'ed25519' || typeof keyId !== 'string' ||
      !/^[a-zA-Z0-9_-]{1,64}$/.test(keyId) || !Number.isSafeInteger(now)) {
    throw new Error('invalid-issuer');
  }
  const data = Buffer.from(JSON.stringify(payload), 'utf8');
  const envelope = JSON.stringify({key_id:keyId, payload:data.toString('base64'),
    signature:crypto.sign(null,data,privateKey).toString('base64')});
  // Validate against the product's reader, including limits and time constraints.
  verifyPolicy(envelope, {keys:{[keyId]:crypto.createPublicKey(privateKey)},now,
    os:payload.os,arch:payload.arch,appVersion:payload.min_app,
    configSha256:payload.config_sha256,
    floor:{revision:0,digest:null}});
  return envelope;
}
module.exports = {issuePolicy, checkEvidence};

if (require.main === module) {
  try {
    const fs = require('node:fs');
    const path = require('node:path');
    const {spawnSync} = require('node:child_process');
    const secret = process.env.MYCRM_COMPAT_SIGNING_KEY;
    const keyId = process.env.MYCRM_COMPAT_KEY_ID;
    delete process.env.MYCRM_COMPAT_SIGNING_KEY;
    if (typeof secret !== 'string' || secret.length > 4096) throw new Error('invalid key');
    const input = fs.readFileSync(0);
    if (input.length > 16384) throw new Error('invalid input');
    const privateKey = crypto.createPrivateKey(secret);
    const payload = JSON.parse(input.toString('utf8'));
    const sourceSha = process.env.GITHUB_SHA;
    if (process.env.GITHUB_ACTIONS !== 'true' || process.env.GITHUB_REPOSITORY !== 'WJY-ador/personal-mycrm'
        || process.env.GITHUB_REF !== 'refs/heads/main'
        || !['schedule','workflow_dispatch'].includes(process.env.GITHUB_EVENT_NAME)
        || !/^[0-9a-f]{40}$/.test(sourceSha || '')) throw new Error('untrusted-build');
    const head = spawnSync('git',['rev-parse','HEAD'],{encoding:'utf8',timeout:5000});
    if (head.status !== 0 || head.stdout.trim() !== sourceSha) throw new Error('untrusted-build');
    const evidenceDir = process.env.MYCRM_COMPAT_EVIDENCE_DIR;
    if (!evidenceDir || !path.isAbsolute(evidenceDir) || !Array.isArray(payload.versions)
        || !['arm64','x64'].includes(payload.arch)) throw new Error('invalid-evidence');
    const receipts = payload.versions.map(entry => {
      const version = entry && entry.version;
      if (typeof version !== 'string' || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) throw new Error('invalid-evidence');
      const file = path.join(evidenceDir, `codex-probe-${payload.arch}-${version}`, 'compat-receipt.json');
      const info = fs.lstatSync(file);
      if (!info.isFile() || info.isSymbolicLink() || info.size > 16384) throw new Error('invalid-evidence');
      return JSON.parse(fs.readFileSync(file,'utf8'));
    });
    checkEvidence(payload,receipts,sourceSha);
    process.stdout.write(issuePolicy(payload, {privateKey,keyId,now:Math.floor(Date.now()/1000)})+'\n');
  } catch (_) {
    process.stderr.write('compatibility policy issuance failed\n');
    process.exitCode = 1;
  }
}
