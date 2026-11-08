"""consent_signature.py 시험 — desktop/src/consent-signature.cjs 와 바이트 호환인 순수 Ed25519 검증.

실행: python3 server/test_consent_signature.py   (pytest 로도 돈다)
합성 데이터만 쓴다. 키는 시험 안에서 Ed25519PrivateKey.generate() 로 만들고 버린다.
예외: JS→Python 교차 검증은 합성 고정 시드(0x42 32바이트)와 Node 가 만든 고정 서명 벡터를 쓴다.
DB, 네트워크, 키체인, 실제 사용자 데이터, provider 를 쓰지 않는다. webchat 이나 라우트를 import 하지 않는다.
"""
import base64
import sys
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, x25519  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import consent_signature as c  # noqa: E402

NOW = 1793000000  # epoch 초, 합성
CLAIMS = MappingProxyType({
    "user_id": "u_test_1",
    "device_id": "dev_test_1",
    "session_id": "sess_test_1",
    "provider": "test-provider",
    "model": "test-model-1.0",
    "nonce": "AAAAAAAAAAAAAAAAAAAAAA",  # base64url 22자 = 128비트
    "expires_at": NOW + 300,
})
# desktop/test/consent-signature.test.cjs 의 encoding 시험과 같은 고정 벡터.
JS_VECTOR = (
    b"mycrm.consent.v1\n"
    b'["u_test_1","dev_test_1","sess_test_1","test-provider","test-model-1.0","AAAAAAAAAAAAAAAAAAAAAA",1793000300]'
)
B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# JS→Python 교차 검증용 고정 벡터. 합성 시드(0x42 32바이트)로 Node 에서 만들었다. 실제 키가 아니다.
# 생성: desktop/src/consent-signature.cjs encodeConsent(CLAIMS) 바이트에 crypto.sign(null, ...),
# 공개키는 publicKey.export({type: "spki", format: "der"}) 를 base64url 로.
JS_SEED = b"\x42" * 32
JS_SPKI_B64U = "MCowBQYDK2VwAyEAIVL40Zt5HSRFMkLhXy6rbLfP-ntqXtMAl5YOBpiB2xI"
JS_SIG = "mK7aIJvxtYIwRgxr_MU5RKzOeRStDN6JFc2482V1OZeoJ72FPFKNZ6DAgHQuywSPzSlbayOxZnJ7i95SlovFAQ"


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def spki(public_key) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def keys():
    priv = Ed25519PrivateKey.generate()
    return priv, spki(priv.public_key())


def sign(claims, priv) -> str:
    """desktop signConsent 와 같은 방식: encodeConsent 바이트에 순수 Ed25519, unpadded base64url."""
    return b64u(priv.sign(c.encode_consent(claims)))


def with_(**patch):
    return {**CLAIMS, **patch}


def without(name):
    d = dict(CLAIMS)
    del d[name]
    return d


def verify(claims, sig, pub, now=NOW):
    return c.verify_consent(claims, sig, pub, now_seconds=now)


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


OK = c.Verification(True)
MALFORMED = c.Verification(False, "MALFORMED")
BAD = c.Verification(False, "BAD-SIGNATURE")
EXPIRED = c.Verification(False, "EXPIRED")


def test_binding_constants_match_desktop():
    assert c.DOMAIN == "mycrm.consent.v1"
    assert c.FIELDS == ("user_id", "device_id", "session_id", "provider", "model", "nonce", "expires_at")
    assert isinstance(c.FIELDS, tuple)


def test_encoding_matches_fixed_js_vector():
    out = c.encode_consent(CLAIMS)
    assert type(out) is bytes
    assert out == JS_VECTOR, out


def test_encoding_ignores_key_order_and_mapping_type():
    reversed_ = dict(reversed(list(CLAIMS.items())))
    assert c.encode_consent(reversed_) == JS_VECTOR
    assert c.encode_consent(dict(CLAIMS)) == JS_VECTOR


def test_node_generated_signature_cross_verifies():
    # desktop(Node)이 서명한 바이트를 Python 이 그대로 검증하고, 같은 키로 같은 서명을 낸다.
    pub = b64u_decode(JS_SPKI_B64U)
    assert len(pub) == 44 and b64u(pub) == JS_SPKI_B64U
    assert c.encode_consent(CLAIMS) == JS_VECTOR
    assert verify(CLAIMS, JS_SIG, pub) == OK
    priv = Ed25519PrivateKey.from_private_bytes(JS_SEED)
    assert spki(priv.public_key()) == pub
    assert sign(CLAIMS, priv) == JS_SIG
    assert b64u(priv.sign(JS_VECTOR)) == JS_SIG
    # 같은 벡터라도 claims 한 글자가 바뀌면 거절된다.
    assert verify(with_(nonce="BAAAAAAAAAAAAAAAAAAAAA"), JS_SIG, pub) == BAD


def test_slash_plus_model_round_trips():
    claims = with_(model="claude/opus+latest")
    priv, pub = keys()
    expected = (
        b"mycrm.consent.v1\n"
        b'["u_test_1","dev_test_1","sess_test_1","test-provider","claude/opus+latest","AAAAAAAAAAAAAAAAAAAAAA",1793000300]'
    )
    encoded = c.encode_consent(claims)
    sig = sign(claims, priv)
    assert encoded == expected
    assert verify(claims, sig, pub) == OK


def test_roundtrip_and_signature_shape():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    assert len(sig) == 86 and "=" not in sig
    assert len(b64u_decode(sig)) == 64
    assert verify(CLAIMS, sig, pub) == OK
    # Ed25519 는 결정적이다.
    assert sign(CLAIMS, priv) == sig


def test_domain_separator_is_load_bearing():
    priv, pub = keys()
    bare = JS_VECTOR[len(b"mycrm.consent.v1\n"):]
    assert verify(CLAIMS, b64u(priv.sign(bare)), pub) == BAD


def test_other_key_rejected():
    a, _ = keys()
    _, pub_b = keys()
    assert verify(CLAIMS, sign(CLAIMS, a), pub_b) == BAD


def test_any_field_tamper_breaks_signature():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    changed = {
        "user_id": "u_test_2", "device_id": "dev_test_2", "session_id": "sess_test_2",
        "provider": "other-provider", "model": "test-model-2.0",
        "nonce": "BAAAAAAAAAAAAAAAAAAAAA", "expires_at": NOW + 301,
    }
    assert tuple(changed) == c.FIELDS
    for k, v in changed.items():
        assert verify(with_(**{k: v}), sig, pub) == BAD, k


def test_tampered_signature_rejected():
    priv, pub = keys()
    raw = bytearray(b64u_decode(sign(CLAIMS, priv)))
    raw[10] ^= 1
    assert verify(CLAIMS, b64u(bytes(raw)), pub) == BAD


def test_expiry_boundary_matches_desktop():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    exp = CLAIMS["expires_at"]
    assert verify(CLAIMS, sig, pub, exp - 1) == OK
    assert verify(CLAIMS, sig, pub, exp) == EXPIRED
    assert verify(CLAIMS, sig, pub, exp + 3600) == EXPIRED
    assert verify(CLAIMS, sig, pub, 0) == OK


def test_bad_signature_wins_over_expiry():
    # desktop 과 같은 순서: 서명 검증이 만료 판정보다 먼저다.
    priv, pub = keys()
    other, _ = keys()
    exp = CLAIMS["expires_at"]
    assert verify(CLAIMS, sign(CLAIMS, other), pub, exp + 1) == BAD


def test_malformed_claims():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    bad = [
        None, "claims", 42, [], list(CLAIMS.values()), tuple(CLAIMS.items()),
        *[without(n) for n in c.FIELDS],
        with_(extra="x"),
        {**dict(CLAIMS), 1: "x"},
        # id
        with_(user_id=""), with_(user_id="a b"), with_(user_id="x" * 129), with_(user_id=7),
        with_(user_id="uü"), with_(user_id="u١"), with_(user_id="u_test_1\n"),
        with_(device_id="dev\n1"), with_(session_id=None),
        # provider, model
        with_(provider=""), with_(provider="Test-Provider"), with_(provider="p" * 33),
        with_(model=""), with_(model="a b"), with_(model="m" * 129), with_(model="claude/opus+latest\n"),
        # nonce: base64url 22..128자
        with_(nonce="abc"), with_(nonce="A" * 21), with_(nonce="A" * 129),
        with_(nonce="AAAAAAAAAAAAAAAAAAAAAA=="), with_(nonce="AAAAAAAAAAAAAAAAAAAA+/"),
        # expires_at: 양의 safe integer, 정확히 int
        with_(expires_at=str(NOW + 300)), with_(expires_at=NOW + 0.5), with_(expires_at=0),
        with_(expires_at=-1), with_(expires_at=float("nan")), with_(expires_at=float("inf")),
        with_(expires_at=2**53), with_(expires_at=True), with_(expires_at=float(NOW + 300)),
        with_(expires_at=None),
    ]
    for b in bad:
        assert verify(b, sig, pub) == MALFORMED, repr(b)
        assert raises(TypeError, lambda b=b: c.encode_consent(b)), repr(b)


def test_malformed_signatures_including_non_canonical_alias():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    # 86자의 마지막 글자는 서명 2비트와 padding 4비트를 담는다. padding 비트를 바꾸면 같은 64바이트로 풀린다.
    alias = sig[:85] + B64URL[B64URL.index(sig[85]) ^ 1]
    assert alias != sig
    assert base64.urlsafe_b64decode(alias + "==") == b64u_decode(sig)
    bad = [
        "", sig[:85], sig + "A", sig + "==", "+" + sig[1:], "!" * 86, alias, sig + "\n",
        b64u_decode(sig), sig.encode("ascii"), None, 42,
    ]
    for s in bad:
        assert verify(CLAIMS, s, pub) == MALFORMED, repr(s)


def test_public_key_must_be_ed25519_spki_der_bytes():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    x_pub = spki(x25519.X25519PrivateKey.generate().public_key())  # 같은 44바이트지만 X25519
    ec_pub = spki(ec.generate_private_key(ec.SECP256R1()).public_key())
    pkcs8 = priv.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    bad = [
        x_pub, ec_pub, pkcs8, raw_pub, pub[:-1], pub + b"\x00", b"\x00" * 44,
        bytearray(pub), memoryview(pub), b64u(pub), priv.public_key(), priv, None,
    ]
    for k in bad:
        assert raises(TypeError, lambda k=k: verify(CLAIMS, sig, k)), repr(k)
    assert verify(CLAIMS, sig, pub) == OK


def test_clock_is_required_and_strict():
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    assert raises(TypeError, lambda: c.verify_consent(CLAIMS, sig, pub))
    for n in [None, str(NOW), NOW + 0.5, float(NOW), float("nan"), -1, 2**53, True]:
        assert raises(TypeError, lambda n=n: verify(CLAIMS, sig, pub, n)), repr(n)


def test_programmer_errors_before_malformed():
    # desktop 처럼 키와 시계 오류는 claims 형식보다 먼저 TypeError 로 드러난다.
    assert raises(TypeError, lambda: verify(None, None, b"\x00"))
    _, pub = keys()
    assert raises(TypeError, lambda: verify(None, None, pub, None))


def test_replay_is_not_blocked_here():
    # 문서화된 한계: 상태가 없으므로 같은 서명이 만료 전까지 계속 통과한다. 소비는 서버 몫이다.
    priv, pub = keys()
    sig = sign(CLAIMS, priv)
    for i in range(3):
        assert verify(CLAIMS, sig, pub, NOW + i) == OK
    assert not hasattr(c, "consume")


def test_inputs_not_mutated():
    priv, pub = keys()
    claims = dict(CLAIMS)
    before = dict(claims)
    sig = sign(claims, priv)
    verify(claims, sig, pub)
    assert claims == before


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"전부 통과({len(tests)}건)")
