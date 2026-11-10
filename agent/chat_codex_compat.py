"""Fail-closed verification of signed compatibility policies.

This is a verification primitive, not an execution grant. The caller must use
an application-pinned trust key and independently protected monotonic floor.
It must bind each allowed version to the actual executable and its runtime.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

_MAX = 16384
_VERSION = re.compile(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\Z')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_KEY_ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


def _bad():
    raise ValueError('invalid-compatibility-policy')


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _bad()
        result[key] = value
    return result


def _parse(raw):
    try:
        return json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_object_pairs,
                          parse_constant=lambda _: _bad())
    except (UnicodeError, json.JSONDecodeError, TypeError, RecursionError):
        _bad()


def _number(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def _version(value):
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        _bad()
    return tuple(map(int, match.groups()))


def _base64(value):
    if not isinstance(value, str) or len(value) > (_MAX * 4 // 3 + 8):
        _bad()
    try:
        encoded = value.encode('ascii', 'strict')
        result = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError, binascii.Error):
        _bad()
    if base64.b64encode(result) != encoded:
        _bad()
    return result


def verify_policy(raw, *, keys, now, os_name, arch, app_version, config_sha256, floor):
    """Return signed versions and checkpoint or raise ValueError, never grant launch."""
    if not isinstance(raw, bytes) or len(raw) > _MAX or not _number(now):
        _bad()
    if not isinstance(floor, dict) or set(floor) != {'revision', 'digest'} or not _number(floor['revision']):
        _bad()
    if floor['revision'] == 0:
        if floor['digest'] is not None:
            _bad()
    elif not isinstance(floor['digest'], str) or not _HEX.fullmatch(floor['digest']):
        _bad()
    env = _parse(raw)
    if not isinstance(env, dict) or set(env) != {'key_id', 'payload', 'signature'}:
        _bad()
    key_id = env['key_id']
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id) or not isinstance(keys, dict):
        _bad()
    key = keys.get(key_id)
    if not isinstance(key, bytes) or len(key) != 32:
        _bad()
    data, sig = _base64(env['payload']), _base64(env['signature'])
    if len(data) > _MAX or len(sig) != 64:
        _bad()
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        raise ValueError('compatibility-crypto-unavailable') from None
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(sig, data)
    except (InvalidSignature, ValueError):
        _bad()
    policy = _parse(data)
    if not isinstance(policy, dict) or set(policy) != {'schema', 'revision', 'issued_at', 'expires_at',
                                                      'os', 'arch', 'min_app', 'source_sha',
                                                      'config_sha256', 'versions'}:
        _bad()
    if type(policy['schema']) is not int or policy['schema'] != 2 or not _number(policy['revision']) or policy['revision'] < 1:
        _bad()
    issued, expires = policy['issued_at'], policy['expires_at']
    if (not _number(issued) or not _number(expires) or issued > now or expires < issued
            or expires - issued > 90 * 86400 or policy['os'] != os_name or policy['arch'] != arch
            or not isinstance(policy['source_sha'], str) or not re.fullmatch(r'[0-9a-f]{40}', policy['source_sha'])
            or not isinstance(config_sha256, str) or not _HEX.fullmatch(config_sha256)
            or policy['config_sha256'] != config_sha256
            or _version(app_version) < _version(policy['min_app'])):
        _bad()
    if expires <= now:
        raise ValueError('compatibility-policy-expired')
    versions = policy['versions']
    if not isinstance(versions, list) or len(versions) > 128:
        _bad()
    for item in versions:
        if (not isinstance(item, dict) or set(item) != {'version', 'native_sha256', 'host_sha256'}
                or not isinstance(item['native_sha256'], str) or not _HEX.fullmatch(item['native_sha256'])
                or not isinstance(item['host_sha256'], str) or not _HEX.fullmatch(item['host_sha256'])):
            _bad()
        _version(item['version'])
    if len({item['version'] for item in versions}) != len(versions):
        _bad()
    digest = hashlib.sha256(data).hexdigest()
    if policy['revision'] < floor['revision'] or (policy['revision'] == floor['revision'] and digest != floor['digest']):
        _bad()
    return {'versions': list(versions), 'checkpoint': {'revision': policy['revision'], 'digest': digest}}


def accept_policy(raw, *, keys, now, os_name, arch, app_version, config_sha256, store, lock):
    """Verify and persist a checkpoint under a caller-provided cross-process lock.

    This primitive is not a production authorization: the caller still must
    supply pinned public keys, independently protect the initial floor and
    bind the execution artifact and its runtime to the policy. Deleting or
    restoring the entire credential store can defeat local rollback protection.
    """
    if (not isinstance(os_name, str) or not re.fullmatch(r'[a-z]{1,16}', os_name)
            or not isinstance(arch, str) or not re.fullmatch(r'[a-z0-9_]{1,16}', arch)
            or not isinstance(config_sha256, str) or not _HEX.fullmatch(config_sha256)):
        _bad()
    account = f'codex-compat-checkpoint-{os_name}-{arch}-{config_sha256}'
    with lock:
        previous = store.get(account)
        if previous is None:
            floor = {'revision': 0, 'digest': None}
        else:
            if not isinstance(previous, str):
                _bad()
            parts = previous.split('-', 1)
            if (len(parts) != 2 or not re.fullmatch(r'[1-9][0-9]{0,15}', parts[0])
                    or not _HEX.fullmatch(parts[1])):
                _bad()
            floor = {'revision': int(parts[0]), 'digest': parts[1]}
            if not _number(floor['revision']):
                _bad()
        result = verify_policy(raw, keys=keys, now=now, os_name=os_name,
                               arch=arch, app_version=app_version,
                               config_sha256=config_sha256, floor=floor)
        checkpoint = result['checkpoint']
        encoded = f"{checkpoint['revision']}-{checkpoint['digest']}"
        if previous != encoded:
            store.set(account, encoded)
            if store.get(account) != encoded:
                _bad()
        return result
