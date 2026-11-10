"""Deterministic identity of the sidecar inputs exercised by CLI probes."""
import hashlib
import json
import re
from pathlib import Path


def digest_input_hashes(hashes):
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('invalid-build-inputs')
    for name, value in hashes.items():
        if (not isinstance(name, str) or not re.fullmatch(r'agent/[A-Za-z0-9_./-]+\.py', name)
                or '..' in name.split('/') or not isinstance(value, str)
                or not re.fullmatch(r'[0-9a-f]{64}', value)):
            raise ValueError('invalid-build-inputs')
    raw = json.dumps(hashes, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hashlib.sha256(raw).hexdigest()


def source_fingerprint(root):
    root = Path(root)
    names = json.loads((root / 'packaging/agent-files.json').read_text(encoding='utf-8'))
    if not isinstance(names, list) or not names or len(set(names)) != len(names):
        raise ValueError('invalid-build-inputs')
    hashes = {}
    for name in names:
        if (not isinstance(name, str) or not re.fullmatch(r'agent/[A-Za-z0-9_./-]+\.py', name)
                or '..' in name.split('/')):
            raise ValueError('invalid-build-inputs')
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('invalid-build-inputs')
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest_input_hashes(hashes)
