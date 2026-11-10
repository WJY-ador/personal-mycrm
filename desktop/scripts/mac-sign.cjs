'use strict';
// electron-builder mac.sign hook. Not bundled: build.files is src/** and package.json only.
//
// With MYCRM_MAC_SIGN_SHA1 and MYCRM_MAC_SIGN_KEYCHAIN set (release builds; see packaging/README.md),
// the whole app, sidecar included, is signed with the self-signed release certificate from that keychain.
// The designated requirement then reads `certificate root = H"<sha1>"` and stays the same across versions,
// which Squirrel.Mac needs to accept an update. electron-builder cannot find an untrusted certificate
// on its own, so the identity and keychain are passed explicitly.
//
// With neither set, the options pass through unchanged: identity "-" (ad-hoc), the same result as before.
const { signAsync } = require('@electron/osx-sign');

const SHA1 = /^[0-9A-Fa-f]{40}$/;

function releaseIdentity(env) {
  const identity = env.MYCRM_MAC_SIGN_SHA1 || '';
  const keychain = env.MYCRM_MAC_SIGN_KEYCHAIN || '';
  if (!identity && !keychain) return null;
  if (!identity || !keychain) throw new Error('mac sign: set both MYCRM_MAC_SIGN_SHA1 and MYCRM_MAC_SIGN_KEYCHAIN, or neither');
  if (!SHA1.test(identity)) throw new Error('mac sign: MYCRM_MAC_SIGN_SHA1 must be a 40-hex certificate SHA-1');
  return { identity: identity.toUpperCase(), keychain };
}

function create(signer, env) {
  return async function macSign(opts) {
    const release = releaseIdentity(env);
    if (!release) return signer(opts);
    // identityValidation false: the certificate is not trusted, so osx-sign must not look it up.
    // Timestamps stay as osx-sign does them per file (Apple's timestamp service), as in the update spike.
    return signer({ ...opts, ...release, identityValidation: false });
  };
}

module.exports = create(opts => signAsync(opts), process.env);
module.exports.create = create;
module.exports.releaseIdentity = releaseIdentity;
