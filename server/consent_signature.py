"""Ed25519 consent 서명 검증(순수) — desktop/src/consent-signature.cjs 와 바이트 단위 호환.

범위: 인코딩과 검증만 한다. 키를 만들거나 저장, 등록, 전송하지 않는다. I/O, 네트워크, 전역 상태가 없다.
시계는 호출자가 now_seconds(정수 epoch 초)로 넣는다. time.time() 을 읽지 않는다.

연결 상태: 이 모듈은 webchat, 라우트, provider, grant 어디에도 연결하지 않았다. 설치 키 bootstrap 이 없으므로
provider/grant 동작은 그대로 fail-closed 다. 연결은 별도 결정이다.

서명 바이트(desktop 과 동일):
    DOMAIN + "\\n" + JSON.stringify([user_id, device_id, session_id, provider, model, nonce, expires_at])
값은 정규식으로 ASCII 문자만 허용하므로 JSON 이스케이프가 생기지 않고, expires_at 은 safe integer 라
Python json.dumps(separators=(",", ":")) 결과가 JS JSON.stringify 와 같다.

공개키 형식(선택): Ed25519 SubjectPublicKeyInfo DER 원본 bytes(44바이트).
Node 에서는 publicKey.export({type: "spki", format: "der"}) 결과와 같다. 저장, 전송용 인코딩
(base64url 등)을 푸는 일은 호출자 몫이다. bytes 가 아니거나, Ed25519 가 아니거나, 재직렬화가
입력과 다르면 TypeError(프로그래머 오류) — desktop 의 KeyObject 타입 검사와 같은 자리다.

Python 쪽이 desktop 보다 좁게 받는 곳(호환 방향은 유지):
- 문자열 값은 정확히 str, expires_at 과 now_seconds 는 정확히 int 만 받는다. bool 과 float 는 거절한다.
  JS 에는 1793000300.0 과 1793000300 의 구분이 없지만 Python json.dumps 는 "1793000300.0" 을 내므로
  float 를 받으면 서명 바이트가 어긋난다. JSON 으로 받은 정수는 json.loads 가 int 로 주므로 영향이 없다.
- claims 는 Mapping 이어야 하고, 키는 정확히 FIELDS 7개(모두 str)여야 한다. 값은 items() 로 한 번만 읽어
  튜플로 고정한 뒤 그 튜플만 검사, 서명 검증에 쓴다.

결과 순서(desktop 과 동일): 키, 시계 검사(TypeError) → MALFORMED(claims, 서명 형식) → BAD-SIGNATURE → EXPIRED.
만료: now_seconds < expires_at 일 때만 유효하다. now_seconds == expires_at 부터 EXPIRED.

재생(replay): 이 모듈은 상태가 없어 재생을 막지 않는다. 같은 (claims, signature) 는 expires_at 전까지
매번 통과한다. 서버가 nonce 기준으로 grant 를 한 트랜잭션 안에서 정확히 한 번 소비해야 한다.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = "mycrm.consent.v1"
FIELDS = ("user_id", "device_id", "session_id", "provider", "model", "nonce", "expires_at")

MAX_SAFE_INTEGER = 2**53 - 1  # JS Number.MAX_SAFE_INTEGER
SPKI_ED25519_LEN = 44
SIGNATURE_LEN = 64

MALFORMED = "MALFORMED"
BAD_SIGNATURE = "BAD-SIGNATURE"
EXPIRED = "EXPIRED"

# desktop 정규식과 같은 문자 집합. JS 의 ^...$(m 플래그 없음)는 끝 줄바꿈을 허용하지 않으므로
# Python 에서는 fullmatch 로 맞춘다(re 의 $ 는 끝 \n 앞에서도 맞기 때문).
_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_PROVIDER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
_MODEL_RE = re.compile(r"[A-Za-z0-9._:/+-]{1,128}")
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{22,128}")
_SIG_RE = re.compile(r"[A-Za-z0-9_-]{86}")


@dataclass(frozen=True)
class Verification:
    """verify_consent 결과. ok=True 면 code 는 None, 아니면 MALFORMED, BAD-SIGNATURE, EXPIRED 중 하나."""

    ok: bool
    code: str | None = None


VALID = Verification(True)


def _is_safe_int(v: object) -> bool:
    return type(v) is int and 0 < v <= MAX_SAFE_INTEGER


def _str_check(rx: re.Pattern[str]):
    return lambda v: type(v) is str and rx.fullmatch(v) is not None


_CHECKS = {
    "user_id": _str_check(_ID_RE),
    "device_id": _str_check(_ID_RE),
    "session_id": _str_check(_ID_RE),
    "provider": _str_check(_PROVIDER_RE),
    "model": _str_check(_MODEL_RE),
    "nonce": _str_check(_NONCE_RE),
    "expires_at": _is_safe_int,
}


def _snapshot(claims: object) -> tuple | None:
    """FIELDS 순서의 불변 튜플, 형식이 틀리면 None."""
    if not isinstance(claims, Mapping):
        return None
    items = tuple(claims.items())
    if len(items) != len(FIELDS):
        return None
    values: dict[str, object] = {}
    for k, v in items:
        if type(k) is not str or k in values:
            return None
        values[k] = v
    if set(values) != set(FIELDS):
        return None
    out = []
    for name in FIELDS:
        v = values[name]
        if not _CHECKS[name](v):
            return None
        out.append(v)
    return tuple(out)


def _bytes_of(t: tuple) -> bytes:
    return (DOMAIN + "\n" + json.dumps(list(t), separators=(",", ":"), ensure_ascii=True)).encode("utf-8")


def encode_consent(claims: Mapping) -> bytes:
    """서명 대상 바이트. desktop encodeConsent 와 같은 바이트를 낸다. 형식이 틀리면 TypeError."""
    t = _snapshot(claims)
    if t is None:
        raise TypeError("consent claims are malformed")
    return _bytes_of(t)


def _decode_signature(sig: object) -> bytes | None:
    """정확히 64바이트의 canonical unpadded base64url 이면 원본 bytes, 아니면 None."""
    if type(sig) is not str or _SIG_RE.fullmatch(sig) is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(sig + "==")
    except (binascii.Error, ValueError):
        return None
    if len(raw) != SIGNATURE_LEN:
        return None
    # 마지막 글자의 padding 비트가 0 이 아니면 같은 64바이트로 풀리는 별칭이다. 재인코딩 비교로 거절한다.
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != sig:
        return None
    return raw


def _load_public_key(spki_der: object) -> Ed25519PublicKey:
    if type(spki_der) is not bytes or len(spki_der) != SPKI_ED25519_LEN:
        raise TypeError("expected Ed25519 SubjectPublicKeyInfo DER bytes (44 bytes)")
    try:
        key = serialization.load_der_public_key(spki_der)
    except (ValueError, TypeError, UnsupportedAlgorithm) as e:
        raise TypeError("expected Ed25519 SubjectPublicKeyInfo DER bytes") from e
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("expected an Ed25519 public key")
    canonical = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if canonical != spki_der:
        raise TypeError("public key DER is not canonical SubjectPublicKeyInfo")
    return key


def _read_now(now_seconds: object) -> int:
    if type(now_seconds) is not int or not (0 <= now_seconds <= MAX_SAFE_INTEGER):
        raise TypeError("now_seconds must be a non-negative integer in epoch seconds")
    return now_seconds


def verify_consent(claims: Mapping, signature: str, public_key_spki_der: bytes, *, now_seconds: int) -> Verification:
    """desktop verifyConsent 와 같은 판정. 프로그래머 오류(키 형식, 시계)는 TypeError."""
    key = _load_public_key(public_key_spki_der)
    now = _read_now(now_seconds)
    t = _snapshot(claims)
    if t is None:
        return Verification(False, MALFORMED)
    raw = _decode_signature(signature)
    if raw is None:
        return Verification(False, MALFORMED)
    try:
        key.verify(raw, _bytes_of(t))
    except (InvalidSignature, ValueError):
        return Verification(False, BAD_SIGNATURE)
    if not t[6] > now:
        return Verification(False, EXPIRED)
    return VALID
