// OS-protected storage for the desktop consent signing key.
//
// This module is deliberately not wired into the app yet. It creates no key unless the caller
// supplies Electron safeStorage, and it fails closed unless encryption is explicitly available.
// It never imports Electron, connects to a service, or returns a private key as text.
//
// The file contains only safeStorage ciphertext. The decrypted payload contains a canonical
// self-check and the public key so that safeStorage backends without authenticated encryption
// still fail closed on corruption or tampering. This self-check detects changes; it is not a
// substitute for safeStorage encryption or an OS-protected key.
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const OUTER_VERSION = 1;
const INNER_VERSION = 1;
const INNER_DOMAIN = 'mycrm.desktop.consent-private-key.v1';
const SAFE_BACKENDS = new Set(['gnome_libsecret', 'kwallet', 'kwallet5', 'kwallet6']);

function fail(message = 'consent key storage unavailable') {
  // Do not attach lower-level errors. safeStorage may include arguments in its messages.
  throw new Error(message);
}

function validateSafeStorage(safeStorage, platform = process.platform) {
  if (!safeStorage || typeof safeStorage.isEncryptionAvailable !== 'function') {
    fail('OS encryption availability cannot be confirmed');
  }
  let available;
  try {
    available = safeStorage.isEncryptionAvailable();
  } catch {
    fail('OS encryption availability cannot be confirmed');
  }
  if (available !== true) fail('OS encryption is unavailable');

  // Electron documents this backend probe for Linux only. On macOS,
  // isEncryptionAvailable() means Keychain is available; on other platforms
  // this Linux-only method may return an unrelated value.
  if (platform === 'linux' && safeStorage.getSelectedStorageBackend !== undefined) {
    if (typeof safeStorage.getSelectedStorageBackend !== 'function') {
      fail('OS encryption backend cannot be confirmed');
    }
    let backend;
    try {
      backend = safeStorage.getSelectedStorageBackend();
    } catch {
      fail('OS encryption backend cannot be confirmed');
    }
    if (typeof backend !== 'string' || !SAFE_BACKENDS.has(backend)) {
      fail('OS encryption backend is not protected');
    }
  }

  if (typeof safeStorage.encryptString !== 'function' || typeof safeStorage.decryptString !== 'function') {
    fail('OS encryption functions are unavailable');
  }
}

function validateOptions(options) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) {
    fail('consent key storage options are invalid');
  }
  const { safeStorage, filePath } = options;
  if (typeof filePath !== 'string' || !path.isAbsolute(filePath) || filePath.trim() !== filePath) {
    fail('consent key file path is invalid');
  }
  validateSafeStorage(safeStorage, options.platform);
  const keyGenerator = options.keyGenerator === undefined
    ? () => crypto.generateKeyPairSync('ed25519')
    : options.keyGenerator;
  if (typeof keyGenerator !== 'function') fail('consent key generator is invalid');
  return { safeStorage, filePath, keyGenerator };
}

function isKeyObject(key, type) {
  return key instanceof crypto.KeyObject
    && key.type === type
    && key.asymmetricKeyType === 'ed25519';
}

function spkiDer(key) {
  return key.export({ type: 'spki', format: 'der' });
}

function validatePair(pair) {
  if (!pair || !isKeyObject(pair.privateKey, 'private') || !isKeyObject(pair.publicKey, 'public')) {
    fail('consent key generator did not return an Ed25519 keypair');
  }
  let derived;
  try {
    derived = crypto.createPublicKey(pair.privateKey);
  } catch {
    fail('consent keypair is invalid');
  }
  const supplied = spkiDer(pair.publicKey);
  const fromPrivate = spkiDer(derived);
  if (supplied.length !== fromPrivate.length || !crypto.timingSafeEqual(supplied, fromPrivate)) {
    fail('consent keypair does not match');
  }
  return Object.freeze({ publicKey: pair.publicKey, privateKey: pair.privateKey });
}

function canonicalBase64(value, { minBytes = 1 } = {}) {
  if (typeof value !== 'string' || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    return null;
  }
  const bytes = Buffer.from(value, 'base64');
  if (bytes.length < minBytes || bytes.toString('base64') !== value) return null;
  return bytes;
}

function exactObject(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const own = Reflect.ownKeys(value);
  return own.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function payloadFor(pair) {
  let privatePem;
  try {
    privatePem = pair.privateKey.export({ type: 'pkcs8', format: 'pem' });
  } catch {
    fail('consent private key cannot be encoded');
  }
  const publicDer = spkiDer(pair.publicKey);
  const publicKey = publicDer.toString('base64');
  const digest = crypto.createHash('sha256')
    .update(INNER_DOMAIN, 'utf8')
    .update('\n', 'utf8')
    .update(privatePem, 'utf8')
    .update('\n', 'utf8')
    .update(publicKey, 'ascii')
    .digest('base64');
  return JSON.stringify({ v: INNER_VERSION, alg: 'ed25519', privateKey: privatePem, publicKey, digest });
}

function pairFromPayload(plaintext) {
  if (typeof plaintext !== 'string' || plaintext.length === 0) fail('stored consent key is invalid');
  let payload;
  try {
    payload = JSON.parse(plaintext);
  } catch {
    fail('stored consent key is invalid');
  }
  if (!exactObject(payload, ['v', 'alg', 'privateKey', 'publicKey', 'digest'])
      || payload.v !== INNER_VERSION
      || payload.alg !== 'ed25519'
      || typeof payload.privateKey !== 'string'
      || typeof payload.publicKey !== 'string'
      || typeof payload.digest !== 'string'
      || JSON.stringify(payload) !== plaintext) {
    fail('stored consent key is invalid');
  }

  const publicBytes = canonicalBase64(payload.publicKey, { minBytes: 1 });
  const digestBytes = canonicalBase64(payload.digest, { minBytes: 32 });
  if (!publicBytes || publicBytes.length !== 44 || !digestBytes || digestBytes.length !== 32) {
    fail('stored consent key is invalid');
  }

  const expectedDigest = crypto.createHash('sha256')
    .update(INNER_DOMAIN, 'utf8')
    .update('\n', 'utf8')
    .update(payload.privateKey, 'utf8')
    .update('\n', 'utf8')
    .update(payload.publicKey, 'ascii')
    .digest();
  if (!crypto.timingSafeEqual(digestBytes, expectedDigest)) fail('stored consent key is invalid');

  let privateKey;
  let publicKey;
  try {
    privateKey = crypto.createPrivateKey(payload.privateKey);
    publicKey = crypto.createPublicKey(privateKey);
  } catch {
    fail('stored consent key is invalid');
  }
  if (!isKeyObject(privateKey, 'private') || !isKeyObject(publicKey, 'public')) {
    fail('stored consent key is invalid');
  }
  let storedPublic;
  try {
    storedPublic = spkiDer(crypto.createPublicKey({ key: publicBytes, type: 'spki', format: 'der' }));
  } catch {
    fail('stored consent key is invalid');
  }
  const derivedPublic = spkiDer(publicKey);
  if (storedPublic.length !== derivedPublic.length || !crypto.timingSafeEqual(storedPublic, derivedPublic)) {
    fail('stored consent key is invalid');
  }
  return Object.freeze({ publicKey, privateKey });
}

async function readExisting(filePath, safeStorage) {
  let stat;
  try {
    stat = await fs.lstat(filePath);
  } catch (error) {
    if (error && error.code === 'ENOENT') return null;
    fail('stored consent key cannot be read');
  }
  if (!stat.isFile() || stat.isSymbolicLink()) fail('stored consent key file is not a regular file');
  if (process.platform !== 'win32' && (stat.mode & 0o077) !== 0) {
    fail('stored consent key file permissions are too broad');
  }

  let raw;
  try {
    raw = await fs.readFile(filePath, 'utf8');
  } catch {
    fail('stored consent key cannot be read');
  }
  let envelope;
  try {
    envelope = JSON.parse(raw);
  } catch {
    fail('stored consent key envelope is invalid');
  }
  if (!exactObject(envelope, ['v', 'alg', 'ciphertext'])
      || envelope.v !== OUTER_VERSION
      || envelope.alg !== 'ed25519'
      || typeof envelope.ciphertext !== 'string'
      || JSON.stringify(envelope) !== raw) {
    fail('stored consent key envelope is invalid');
  }
  const ciphertext = canonicalBase64(envelope.ciphertext, { minBytes: 1 });
  if (!ciphertext) fail('stored consent key ciphertext is invalid');

  let plaintext;
  try {
    plaintext = safeStorage.decryptString(ciphertext);
  } catch {
    fail('stored consent key cannot be decrypted');
  }
  return pairFromPayload(plaintext);
}

async function writeNew(filePath, safeStorage, keyGenerator) {
  const directory = path.dirname(filePath);
  const tempName = `${path.basename(filePath)}.tmp-${process.pid}-${crypto.randomBytes(12).toString('hex')}`;
  const tempPath = path.join(directory, tempName);
  let tempHandle;
  let lockHandle;
  const lockPath = `${filePath}.lock`;
  try {
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    // A stale lock deliberately fails closed; another app process must not create competing keys.
    lockHandle = await fs.open(lockPath, 'wx', 0o600);

    // Recheck under the exclusive lock in case another process completed first.
    const existing = await readExisting(filePath, safeStorage);
    if (existing) return existing;

    let generated;
    try {
      generated = await keyGenerator();
    } catch {
      fail('consent key generation failed');
    }
    const pair = validatePair(generated);
    let ciphertext;
    try {
      ciphertext = safeStorage.encryptString(payloadFor(pair));
    } catch {
      fail('consent key encryption failed');
    }
    if (!Buffer.isBuffer(ciphertext) || ciphertext.length === 0) fail('consent key encryption failed');

    const envelope = JSON.stringify({ v: OUTER_VERSION, alg: 'ed25519', ciphertext: ciphertext.toString('base64') });
    tempHandle = await fs.open(tempPath, 'wx', 0o600);
    await tempHandle.writeFile(envelope, { encoding: 'utf8' });
    await tempHandle.sync();
    await tempHandle.close();
    tempHandle = null;
    await fs.rename(tempPath, filePath);
    if (process.platform !== 'win32') await fs.chmod(filePath, 0o600);
    return pair;
  } catch (error) {
    if (error && error.code === 'EEXIST') fail('consent key storage is busy');
    if (error instanceof Error && error.message.startsWith('consent ')) throw error;
    fail('consent key could not be stored');
  } finally {
    if (tempHandle) {
      try { await tempHandle.close(); } catch { /* cleanup only */ }
    }
    try { await fs.unlink(tempPath); } catch { /* absent temp file */ }
    if (lockHandle) {
      try { await lockHandle.close(); } catch { /* cleanup only */ }
      try { await fs.unlink(lockPath); } catch { /* cleanup only */ }
    }
  }
}

async function loadOrCreateKeyPair(options) {
  const { safeStorage, filePath, keyGenerator } = validateOptions(options);
  const existing = await readExisting(filePath, safeStorage);
  if (existing) return existing;
  return writeNew(filePath, safeStorage, keyGenerator);
}

module.exports = Object.freeze({ loadOrCreateKeyPair });
