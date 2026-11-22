"""일회 실행 — 수집기 산출물 → 어댑터 → PC 원문·신원 매핑 → 결정적 변환 → 계약 검증
→ 전송 대기 파일(원자적) → 업로드 → 접수 결과 저장.
"""
from __future__ import annotations

import json
import os
import random
import re
import time

from . import adapters as _adapters
from . import config as _config
from . import contract, hmacid, jcs, keystore, store as _store
from .adapters.base import CollectedPost, Observation, Quarantine
from .adapters import collected as _collected
from .adapters.collected import masked_count


class RunError(RuntimeError):
    pass


def _projection(fields: dict, transform_version: str) -> str:
    """원본 내용의 지문 — 바뀌면 새 개정. 정책 판(policy_revision)은 요청 메타데이터라 넣지 않는다:
    허용 규칙이 바뀌어도 이미 접수된 원본은 새 개정을 만들지 않는다(메인 판정 2026-10-20)."""
    return jcs.sha256_hex({"fields": fields, "transform_version": transform_version})


def stage_activity(st: "_store.Store", cfg: dict, adapter, obs: Observation, hmac_key: bytes | None,
                   counts: dict) -> None:
    ev = st.event_get(adapter.name, obs.dedupe_key)
    if ev is None:
        ev = st.event_create(adapter.name, obs.dedupe_key, "activity", obs.fingerprint, raw_obj=obs.raw)
        counts["new_events"] += 1
    elif ev["fingerprint"] != obs.fingerprint:
        # 같은 중복 기준인데 신원이 달라짐 → 판별 불가, 격리하고 새 개정 안 만듦
        st.quarantine(adapter.name, "identity-changed", obs.dedupe_key)
        counts["quarantined"] += 1
        return
    else:
        try:
            st.raw_update(ev["raw_id"], obs.raw)
        except _store.StoreError:
            pass

    people = []
    if obs.people:
        ns = cfg.get("hmac_namespace")
        if not ns or hmac_key is None:
            raise RunError("hmac key/namespace not configured")
        for provider_code, account_id, role in obs.people:
            h = st.person_hmac(ns, provider_code, account_id,
                               lambda: hmacid.person_hmac(hmac_key, provider_code, account_id))
            people.append({"hmac": h, "role": role})
    fields = {
        "action": obs.action,
        "state": obs.state,
        "occurred_on": obs.occurred_on,
        "observed_on": obs.observed_on,
        "provider": obs.provider,
        "raw_id": ev["raw_id"],
        "people": people,
        "axes": list(obs.axes),
    }
    _stage(st, cfg, ev["original_id"], "activity", adapter.transform_version, "unattended"
           if cfg.get("_execution") == "unattended" else "attended", fields, counts, adapter.name)


COLLECTED_TRANSFORM = "collected-post/1"
AXIS_CODES_FEATURE = "axis_codes"
FEATURES_CHECKED = "server_features_checked"     # 커서 — 서버 기능을 마지막으로 물어본 KST 날짜


# 이미 올린 수집 글에 축 코드를 처음 실어 다시 올리는 개정(재업로드) — 실행당 몫. 업로드 간격(min_interval_sec 6.5초) × 건수가
# 앱의 run-once 시간 한도(600초)를 넘지 않게 state_resync 와 같은 50 으로 나눈다(새 글은 몫과 무관하게 만든다). 남은 것은 다음 실행이 잇는다
AXIS_RESTAGE_PER_RUN = 50


def _axis_restage_full(st, cfg: dict, oid: str, fields: dict) -> bool:
    """이 글이 이미 접수된 원본이고 내용(투영)이 바뀌어 새 개정이 될 참인데, 이번 실행의 재업로드 몫을 다 썼나. 다 안 썼으면 하나 센다."""
    acc = st.latest_accepted(oid)
    if acc is None or st.has_open_revision(oid) or acc["projection_sha"] == _projection(fields, COLLECTED_TRANSFORM):
        return False
    latest = st.latest_revision(oid)
    if latest is not None and latest["projection_sha"] == _projection(fields, COLLECTED_TRANSFORM):
        return False
    n = cfg.setdefault("_axis_restaged", 0)
    if n >= AXIS_RESTAGE_PER_RUN:
        return True
    cfg["_axis_restaged"] = n + 1
    return False


def axis_codes_on(cfg: dict) -> bool:
    """서버가 수집 글 axis_codes 를 받는다고 알렸나(GET /api/imports/device 의 features). 모르면 False — 옛 서버는 그 키를
    CONTRACT-INVALID 로 거절하고, 거절된 판은 같은 내용으로 다시 만들지 않으므로 보내기 전에 정한다."""
    return AXIS_CODES_FEATURE in (cfg.get("server_features") or [])


def stage_collected_post(st: "_store.Store", cfg: dict, adapter, cp: CollectedPost, counts: dict) -> None:
    """수집 글 1건. 원문은 PC 원문 저장소(raw_id)에 두고, 서버엔 cp.fields + raw_id 만 보낸다.
    only_if_sent(버림·만료 등 → state removed)는 이미 개정을 만든 원본에만 보낸다 — 처음 보는 버린 글은 올리지 않는다."""
    ev = st.event_get(adapter.name, cp.dedupe_key)
    if cp.only_if_sent and (ev is None or st.latest_revision(ev["original_id"]) is None):
        counts["not_sent"] += 1
        return
    if ev is None:
        ev = st.event_create(adapter.name, cp.dedupe_key, "collected_post", cp.fingerprint, raw_obj=cp.raw)
        counts["new_events"] += 1
    elif ev["fingerprint"] != cp.fingerprint:
        st.quarantine(adapter.name, "identity-changed", cp.dedupe_key)
        counts["quarantined"] += 1
        return
    else:
        try:
            st.raw_update(ev["raw_id"], cp.raw)
        except _store.StoreError:
            pass
    fields = dict(cp.fields)
    codes = list(cp.axis_codes or [])
    if axis_codes_on(cfg):
        # 서버가 축 코드를 받는다(2026-11-18) — 축은 코드로만 보낸다(옛 axes_map 경로·POLICY-AXIS 대조는 쓰지 않는다).
        # 축이 없는 글은 키를 빼 투영이 옛 판과 같게 둔다(다시 올리지 않는다)
        fields.pop("axes", None)
        if codes:
            fields["axis_codes"] = codes
    fields["raw_id"] = ev["raw_id"]
    oid = ev["original_id"]
    if "axis_codes" in fields and _axis_restage_full(st, cfg, oid, fields):
        counts["deferred_axis"] = counts.get("deferred_axis", 0) + 1     # 이미 올린 글의 축 다시 올리기 — 이번 실행 몫을 다 썼다
        return
    rs = cfg.get("_resync")
    want = rs is not None and rs.wants(oid)
    before, quarantined = counts["staged"], counts["quarantined"]
    _stage(st, cfg, oid, "collected_post", COLLECTED_TRANSFORM,
           "unattended" if cfg.get("_execution") == "unattended" else "attended", fields, counts, adapter.name,
           force=want and rs.can_stage())
    if want:
        if counts["staged"] > before:
            rs.staged_one(oid)        # 같은 필드의 새 개정(또는 내용이 바뀐 새 개정) — 어느 쪽이든 state 를 싣는다
        elif counts["quarantined"] > quarantined:
            st.resync_set(oid, "failed")      # 지금 허용 규칙으로 만들 수 없다(축 등)


# ---- 수집 글 상태 다시 보내기(state_resync, 명세 보강 D3, 메인 판정 가안 B 2026-11-13) ----------------------
# 서버가 이미 올라간 수집 글의 state 를 모른다. 이 판의 첫 실행 때 한 번, 대응표의 수집 글(feed·reactions) 중 서버에 항목이 있는
# 것을 대상으로 올리고, 수집 때 같은 필드의 새 개정(previous = 마지막 접수 개정, 지금 허용 규칙 판)을 만든다. 서버는 반영 내용이
# 같으면 noop 으로 받으며 state 를 채운다. 옛 요청 바이트를 다시 만들지 않는다. 장치 수집 글 하루 한도(500)·max_per_run 안에서
# 새 수집 글 몫을 남기도록 실행당·KST 하루당 만들 수를 나눈다. 입력에서 사라진 행은 같은 필드를 만들 수 없어 unseen 으로 닫는다.
RESYNC_FLAG = "state_resync:2026-11-13"
RESYNC_PER_RUN = 50
RESYNC_PER_DAY = 300


class _Resync:
    def __init__(self, st, day: str):
        self.st, self.day_key = st, "state_resync_day:" + day
        flag = st.cursor_get(RESYNC_FLAG)
        self.active = flag != "done"
        if flag is None:
            st.resync_begin()
            st.cursor_set(RESYNC_FLAG, "started")
        self.day_used = int(st.cursor_get(self.day_key) or 0)
        self.staged = 0
        self.seen = {}               # 어댑터 → 이번 수집에서 본 원본

    def see(self, adapter: str, oid: str) -> None:
        self.seen.setdefault(adapter, set()).add(oid)

    def wants(self, oid: str) -> bool:
        return self.active and self.st.resync_status(oid) == "queued"

    def can_stage(self) -> bool:
        return self.staged < RESYNC_PER_RUN and self.day_used + self.staged < RESYNC_PER_DAY

    def staged_one(self, oid: str) -> None:
        self.st.resync_set(oid, "staged")
        self.staged += 1
        # 하루 몫은 만들 때마다 남긴다 — 실행이 중간에 끊겨도(앱의 600초 종료 등) 다음 실행이 같은 날 몫을 다시 쓰지 않게
        self.st.cursor_set(self.day_key, str(self.day_used + self.staged))

    def collected(self, adapter: str) -> None:
        """그 어댑터의 수집이 끝까지 돌았다 — 보지 못한 대상을 닫는다."""
        if self.active:
            self.st.resync_unseen(adapter, self.seen.get(adapter, set()))

    def finish(self) -> dict:
        """{queued: 이번 실행에 만든 새 개정, sent: 이번 실행에 접수된 수, done: 남은 대상 없음,
        unseen·failed: 보내지 못하고 닫은 대상 누적(입력에서 사라짐 · 거절·지금 규칙으로 못 만듦)}."""
        if self.active:
            sent = self.st.resync_settle()
            done = self.st.resync_remaining() == 0
            if done:
                self.st.cursor_set(RESYNC_FLAG, "done")
        else:
            sent, done = 0, True
        closed = self.st.resync_closed()
        return {"queued": self.staged, "sent": sent, "done": done, "unseen": closed["unseen"], "failed": closed["failed"]}


def _stage(st, cfg, original_id, kind, transform_version, execution, fields, counts, adapter_name,
           force: bool = False) -> None:
    """force: 내용이 같아도 마지막 접수 개정 뒤로 새 개정을 만든다(state_resync). 접수되지 않은 판 뒤로는 만들지 않는다."""
    pr = cfg["policy_revision"]
    proj = _projection(fields, transform_version)
    latest = st.latest_revision(original_id)
    if latest is not None and latest["projection_sha"] == proj and not (force and latest["status"] == "accepted"):
        # 같은 내용: 접수·대기면 변경 없음, 거절·충돌이면 같은 요청을 다시 만들지 않는다
        counts["unchanged" if latest["status"] in ("pending", "accepted", "halted") else "blocked"] += 1
        return
    if st.has_open_revision(original_id):
        counts["waiting"] += 1
        return
    # 이전 판 = 마지막으로 서버에 보낸 판. 「삭제됨」 응답을 받은 판도 accepted 라 여기 잡힌다(서버가 그 판을 기록한다)
    accepted = st.latest_accepted(original_id)
    prev = accepted["revision"] if accepted is not None else None
    if accepted is not None and accepted["projection_sha"] == proj and not force:
        counts["unchanged"] += 1
        return
    rev = _store.new_revision()
    obj = contract.build_request(
        kind=kind, source_instance_id=cfg["source_instance_id"], original_id=original_id, revision=rev,
        previous_revision=prev, execution=execution, transform_version=transform_version,
        policy_revision=pr, fields=fields)
    try:
        body = contract.encode_request(obj, policy=_config.policy_of(cfg))
    except contract.ContractError as e:
        st.quarantine(adapter_name, "contract:" + e.code, original_id)
        counts["quarantined"] += 1
        return
    key = contract.idempotency_key(cfg["source_instance_id"], original_id, rev)
    st.add_revision(original_id=original_id, revision=rev, previous_revision=prev,
                    projection_sha=proj, idem_key=key, body=body)
    counts["staged"] += 1


def stage_self_text(st, cfg, *, adapter_name: str, dedupe_key: str, fingerprint: str, kind: str,
                    transform_version: str, execution: str, fields: dict, counts: dict,
                    identity_text: str | None = None) -> bool:
    """자기 글·요약 요청 생성. 로컬 추가 대조(규칙 7): 매핑에 있는 계정 식별자가 본문에 있으면 격리.
    identity_text = 대조할 글(기본 제목+본문). 수집 인박스 요약은 post_url(이미 collected-post/1 로 가는 남의 글 주소,
    작성자 핸들이 들어 있다)을 빼고 주제 이름·문장만 대조한다."""
    text = identity_text if identity_text is not None else " ".join(str(fields.get(k) or "") for k in ("title", "body"))
    for acct in st.known_account_ids():
        if len(acct) >= 3 and acct in text:
            st.quarantine(adapter_name, "local-identity-match", dedupe_key)
            counts["quarantined"] += 1
            return False
    ev = st.event_get(adapter_name, dedupe_key)
    if ev is None:
        ev = st.event_create(adapter_name, dedupe_key, kind, fingerprint, raw_obj=None)
        counts["new_events"] += 1
    before = counts["staged"]
    _stage(st, cfg, ev["original_id"], kind, transform_version, execution, fields, counts, adapter_name)
    return counts["staged"] > before


def refresh_policy(paths, st, cfg: dict, up) -> dict:
    """업로드가 POLICY-STALE 로 멈췄을 때 1회 — 같은 토큰으로 GET /api/imports/device 를 불러 허용 규칙을 다시 받고,
    설정을 갱신한 뒤 아직 접수되지 않은 전송 대기 요청을 새 정책 판으로 다시 만든다(토큰 재입력 없음).
    입력원·키 공간이 바뀌었으면 고치지 않는다(connect 를 다시 해야 한다). 반환 {"status", ...} — 값·토큰 없음."""
    from .uploader import DeviceError
    try:
        info = up.device()
    except DeviceError as e:
        return {"status": "device-" + e.kind}
    public = {k: v for k, v in cfg.items() if not k.startswith("_")}
    try:
        new = _config.apply_device_info(public, info, expected_stream=cfg.get("source_instance_id"))
    except _config.ConfigError:
        return {"status": "device-mismatch"}
    if new.get("hmac_namespace") != cfg.get("hmac_namespace"):
        return {"status": "namespace-changed"}
    from . import osutil
    st.cursor_set(FEATURES_CHECKED, osutil.kst_now().date().isoformat())   # 이 응답이 서버 기능도 알려 줬다 — 오늘은 다시 묻지 않는다
    if new.get("policy_revision") == cfg.get("policy_revision"):
        # 서버 판이 그대로인데 POLICY-STALE — 고칠 것이 없다. 멈춤 유지. 서버 기능(features)이 바뀌었으면 그것만 저장한다
        if new.get("server_features") != cfg.get("server_features"):
            keep = dict(public, server_features=new.get("server_features"))
            try:
                _config.validate_config(keep)
                _config.save(paths, keep)
                cfg["server_features"] = keep["server_features"]
            except _config.ConfigError:
                pass
        return {"status": "unchanged"}
    try:
        _config.validate_config(new)
    except _config.ConfigError:
        return {"status": "config-invalid"}    # 예: 설정의 likes.axes 가 새 허용 축 밖
    _config.save(paths, new)
    pr, pol = new["policy_revision"], _config.policy_of(new)

    def rebuild(body: bytes):
        obj = json.loads(body.decode("utf-8"))
        obj["policy_revision"] = pr
        fields = {k: v for k, v in obj.items() if k not in contract.COMMON_FIELDS}
        return contract.encode_request(obj, policy=pol), _projection(fields, obj["transform_version"])
    out = st.rebase_pending(rebuild)
    out.update({"status": "ok", "policy_revision": pr})
    cfg.update(new)
    return out


def refresh_features(paths, cfg: dict, up) -> dict:
    """서버 기능(features)만 다시 받아 설정의 server_features 를 맞춘다 — 허용 규칙·정책 판은 건드리지 않는다(그건 refresh_policy 몫).
    옛 서버(features 없음)면 []. 반환 {"status": ok|device-*, "features": [...]} — 값·토큰 없음."""
    from .uploader import DeviceError
    try:
        info = up.device()
    except DeviceError as e:
        return {"status": "device-" + e.kind}
    if not isinstance(info, dict) or info.get("stream_id") != cfg.get("source_instance_id"):
        return {"status": "device-mismatch"}
    feats = info.get("features")
    feats = [f for f in dict.fromkeys(feats) if f in _config.KNOWN_FEATURES] if isinstance(feats, list) else []
    if feats != cfg.get("server_features"):
        public = {k: v for k, v in cfg.items() if not k.startswith("_")}
        public["server_features"] = feats
        try:
            _config.save(paths, public)
        except _config.ConfigError:
            return {"status": "config-invalid"}
        cfg["server_features"] = feats
    return {"status": "ok", "features": feats}


def load_secrets(cfg: dict, ks: keystore.KeyStore, need_hmac: bool):
    sid = cfg.get("source_instance_id")
    if not sid or not cfg.get("server_url"):
        raise RunError("not connected — run `connect` first")
    token = ks.get(_config.token_account(sid))
    if not token:
        raise RunError("upload token missing in keychain — run `connect` again")
    hkey = None
    if need_hmac:
        ns = cfg.get("hmac_namespace")
        if not ns:
            raise RunError("hmac_namespace not configured")
        hk = ks.get(_config.hmac_account(ns))
        if not hk:
            raise RunError("hmac key missing in keychain for this namespace")
        hkey = hmacid.key_from_hex(hk)
    return token, hkey


def collect(st, cfg: dict, hmac_key, counts: dict) -> None:
    for name, section in (cfg.get("adapters") or {}).items():
        if not section.get("enabled"):
            continue
        adapter = _adapters.get(name)            # 차단 입력원은 여기서 TransmissionBlocked
        adapter.check_config(section)            # 골격은 여기서 AdapterNotActive
        for item in adapter.collect(section):
            if isinstance(item, Quarantine):
                st.quarantine(name, item.reason, item.key)
                counts["quarantined"] += 1
            elif isinstance(item, CollectedPost):
                counts["observed"] += 1
                rs = cfg.get("_resync")
                if rs is not None:
                    ev = st.event_get(name, item.dedupe_key)
                    if ev is not None:
                        rs.see(name, ev["original_id"])
                if not _policy_allows(cfg, COLLECTED_TRANSFORM):
                    counts["skipped_policy"] += 1
                    continue
                counts["masked"] += masked_count(item.fields)
                stage_collected_post(st, cfg, adapter, item, counts)
            else:
                counts["observed"] += 1
                if not _policy_allows(cfg, adapter.transform_version, item.action):
                    counts["skipped_policy"] += 1
                    continue
                stage_activity(st, cfg, adapter, item, hmac_key, counts)
        if cfg.get("_resync") is not None and adapter.kind == "collected_post":
            cfg["_resync"].collected(name)


def _policy_allows(cfg: dict, transform: str, action: str | None = None) -> bool:
    """장치 허용 규칙(서버에서 받은 값)에 없는 변환·행동이면 만들지 않는다(sessionwrap 의 skipped=policy 와 같게,
    격리하지 않는다 — 웹 연결 장치에서 켜면 다음 실행에 만든다). 모르면(None) 허용으로 보고 계약 검증에 맡긴다.
    likes(board-likes/1)는 기존 동작(계약 검증에서 격리) 그대로 둔다."""
    if transform == "board-likes/1":
        return True
    tr, ac = cfg.get("allowed_transforms"), cfg.get("allowed_actions")
    if tr is not None and transform not in tr:
        return False
    return not (action is not None and ac is not None and action not in ac)


def _needs_features_check(st, cfg: dict) -> bool:
    """수집 글(feed)을 켰는데 서버가 축 코드를 받는지 아직 모른다 — 하루 한 번(KST) 장치 정보를 물어본다. 대기 요청이 없으면
    POLICY-STALE 이 오지 않아 새 서버를 알아챌 길이 없다(재업로드가 시작되지 않는다). 이미 알면 묻지 않는다."""
    feed = (cfg.get("adapters") or {}).get("feed") or {}
    if not feed.get("enabled") or axis_codes_on(cfg):
        return False
    from . import osutil
    return st.cursor_get(FEATURES_CHECKED) != osutil.kst_now().date().isoformat()


def _policy_missing_transforms(cfg: dict) -> bool:
    """켠 어댑터가 쓰는 변환 중 설정의 허용 변환(allowed_transforms, 서버에서 받은 값)에 없는 것이 있나. 모르면(None) False.
    축 한 장(axis_pages.dir 설정)·수집 인박스 요약(inbox_digest.enabled)도 켠 것으로 본다."""
    allowed = cfg.get("allowed_transforms")
    if allowed is None:
        return False
    need = set()
    if (cfg.get("axis_pages") or {}).get("dir"):
        need.add(contract.AXIS_PAGE_TRANSFORM)
    if (cfg.get("inbox_digest") or {}).get("enabled") is True:
        need.add(contract.INBOX_DIGEST_TRANSFORM)
    for name, section in (cfg.get("adapters") or {}).items():
        if not section.get("enabled") or name not in _adapters.ACTIVE:
            continue
        a = _adapters.ACTIVE[name]
        need.add(a.transform_version)
        if a.kind == "collected_post":
            need.add(COLLECTED_TRANSFORM)
    return bool(need - set(allowed))


# ---- 웹 판별 되돌림(명세 2026-11-13 4절) -------------------------------------------------
WRITE_BACK_MAX_PAGES = 20
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_NO_WRITE_BACK_AFTER = ("auth", "config", "forbidden")    # 업로드가 이 이유로 멈췄으면 판별 목록도 받지 않는다


def _decision(d):
    """판별 한 줄 → (item_id, (state, decided_at) | None). 쓸 수 없는 줄은 None. None 값 = 되돌리지 않는 판별(예: pending)."""
    if not isinstance(d, dict):
        return None
    iid, state, at = d.get("item_id"), d.get("state"), d.get("decided_at")
    if not isinstance(iid, str) or not _ITEM_ID_RE.match(iid):
        return None
    if state not in _collected.WRITE_BACK_STATES:
        return iid, None
    if not isinstance(at, str) or not 1 <= len(at) <= 64 or any(c in at for c in "\r\n\x00"):
        return iid, None
    return iid, (state, at)


def write_back(st, cfg: dict, up, *, min_interval: float = 0.0) -> dict | None:
    """업로드 뒤 — 서버의 사용자 판별 목록을 커서로 이어 받아 feed 입력 파일의 pending 행에 되돌려 쓴다.
    feed.write_back 이 꺼져 있으면 받지도 않는다(커서를 옮기지 않아, 나중에 켜면 그 전 판별부터 받는다). 반환 None(꺼짐) 또는
    {applied, skipped_not_pending, missing, retried, stopped}. 쪽마다 파일 쓰기를 마친 뒤에만 커서를 옮긴다.
    has_more 면 이어 받는다. 요청 사이 min_interval(업로드와 같은 장치 분당 한도). 429 = 다음 실행으로 미룸(stopped rate-limit),
    400 ARG-INVALID = 커서를 버리고 처음부터 한 번. 결과엔 수만 남긴다(항목 ID·원천 ID·경로 없음)."""
    from .uploader import DeviceError
    feed = (cfg.get("adapters") or {}).get("feed") or {}
    if feed.get("write_back") is not True:
        return None
    out = {"applied": 0, "skipped_not_pending": 0, "missing": 0, "retried": 0, "stopped": None}
    if not feed.get("enabled") or not isinstance(feed.get("input_path"), str):
        out["stopped"] = "feed-off"
        return out
    path = os.path.expanduser(feed["input_path"])
    name = "decisions:" + str(cfg.get("source_instance_id"))
    since = st.cursor_get(name)
    reset = False
    for _ in range(WRITE_BACK_MAX_PAGES):
        if min_interval > 0:
            up.sleep(min_interval)
        try:
            page = up.decisions(since)
        except DeviceError as e:
            if e.status == 400 and e.code == "ARG-INVALID" and since and not reset:
                since, reset = None, True        # 서버가 커서를 모른다 — 처음부터 한 번(이미 바꾼 행은 pending 이 아니라 건너뛴다)
                continue
            out["stopped"] = "rate-limit" if e.status == 429 else e.kind + (f"-{e.status}" if e.status else "")
            return out
        latest = {}
        for d in page["decisions"]:
            got = _decision(d)
            if got is not None:
                latest.pop(got[0], None)     # 같은 항목은 목록의 마지막 판별(되돌리기 포함)을 따른다
                latest[got[0]] = got[1]
        changes = {}
        for iid, change in latest.items():
            if change is None:
                continue
            keys = [k for k in st.dedupe_keys_for_target("feed", iid) if k.startswith("feed:")]
            if not keys:
                out["missing"] += 1          # 이 PC 의 feed 에서 올린 항목이 아니다
                continue
            for k in keys:
                changes[k[len("feed:"):]] = change
        if changes:
            try:
                r = _collected.write_back_feed(path, changes)
            except _collected.FileChanged:
                out["retried"] += 1
                out["stopped"] = "file-changed"
                return out
            except OSError:
                out["stopped"] = "input-unreadable"
                return out
            for k in ("applied", "skipped_not_pending", "missing", "retried"):
                out[k] += r[k]
        nxt = page.get("next_cursor")
        if isinstance(nxt, int) and not isinstance(nxt, bool):
            nxt = str(nxt)
        if isinstance(nxt, str) and 1 <= len(nxt) <= 512 and nxt != since:
            st.cursor_set(name, nxt)
            since = nxt
        else:
            if page["decisions"]:
                out["stopped"] = "no-cursor"     # 판별은 받았는데 이어 받을 커서가 없다 — 다음 실행이 같은 쪽을 다시 받는다
            break
        if page.get("has_more") is not True or not page["decisions"]:
            break
    else:
        out["stopped"] = "max-pages"
    return out


def _budget_left(started: float, budget: float) -> float:
    """실행 시작(monotonic)부터 센 업로드 예산의 남은 초. 0 아래로 내려가지 않는다."""
    return max(0.0, budget - (time.monotonic() - started))


def new_counts() -> dict:
    return {"observed": 0, "new_events": 0, "staged": 0, "unchanged": 0, "waiting": 0, "blocked": 0,
            "quarantined": 0, "not_sent": 0, "masked": 0, "skipped_policy": 0}


def run_once(paths, *, ks: keystore.KeyStore, uploader_factory=None, summarizer=None,
             scheduled: bool = False, jitter_max: float = 300.0, sleep=time.sleep, upload: bool = True,
             exec_runner=None, process_started: float | None = None) -> dict:
    """잠금 → (예약 실행이면 0~5분 지연) → 수집·변환·대기 저장 → 요약(켜졌을 때) → 수집 인박스 요약(켜졌을 때) → 업로드.
    exec_runner = 모델 실행기(시험은 가짜). process_started = 프로세스가 시작된 time.monotonic() 값(앱의 600초 종료 기준,
    없으면 이 함수의 시작 시각)."""
    from . import osutil
    from .uploader import UPLOAD_BUDGET_SEC, Uploader

    paths.ensure()
    lock = osutil.FileLock(paths.lock("run"))
    try:
        lock.acquire()
    except osutil.LockBusy:
        return {"skipped": "already-running"}
    try:
        if scheduled and jitter_max > 0:
            sleep(random.uniform(0, jitter_max))
        started = time.monotonic()      # 업로드 시간 예산의 시작(예약 실행의 지연은 빼고 센다)
        cfg = _config.load(paths)
        cfg = dict(cfg)
        cfg["_execution"] = "unattended" if scheduled else "attended"
        st = _store.Store(paths)
        try:
            st.reconcile()
            need_hmac = any(s.get("enabled") for s in (cfg.get("adapters") or {}).values())
            token, hkey = load_secrets(cfg, ks, need_hmac)
            counts = new_counts()
            result = {}
            up = None
            if upload and _policy_missing_transforms(cfg):
                # 켠 어댑터의 변환이 설정의 허용 규칙에 없다 — 웹에서 허용을 켰을 수 있으니 수집 전에 한 번 다시 받는다.
                # (대기 요청이 없으면 POLICY-STALE 이 오지 않아 허용 변경을 알 길이 없다.) 실패해도 이번 실행은 그대로
                up = (uploader_factory or Uploader)(cfg["server_url"], token, timeout=cfg["upload"]["timeout_sec"])
                result["policy_refresh_before"] = refresh_policy(paths, st, cfg, up)
            elif upload and _needs_features_check(st, cfg):
                # 서버 기능(축 코드)을 아직 모른다 — 하루 한 번 기능만 묻는다(정책은 그대로). 실패해도 이번 실행은 그대로
                up = (uploader_factory or Uploader)(cfg["server_url"], token, timeout=cfg["upload"]["timeout_sec"])
                result["features_refresh"] = refresh_features(paths, cfg, up)
                if result["features_refresh"]["status"] == "ok":
                    st.cursor_set(FEATURES_CHECKED, osutil.kst_now().date().isoformat())
            cfg["_resync"] = _Resync(st, osutil.kst_now().date().isoformat())
            from .adapters import axis_pages   # 축 한 장(설정 axis_pages.dir 일 때만) — 수집 글보다 먼저 줄 세운다(재업로드 뒤에 밀리지 않게)
            result["axis_pages"] = axis_pages.collect(st, cfg, counts)
            collect(st, cfg, hkey, counts)
            result["collect"] = counts
            from . import sessionwrap   # 세션 정리 폴더(설정에서 켰을 때만) — 같은 전송 대기·업로드 경로
            result["session_wrap"] = sessionwrap.collect(st, cfg, counts)
            if summarizer is not None:
                result["summary"] = summarizer(st, cfg)
            # 수집 인박스 요약(inbox_digest.enabled 일 때만, 2026-11-22) — 수집 글 뒤에 줄 세운다: 서버가 post_url 을 항목으로 바꾸려면
            # 그 글이 먼저 올라가 있어야 한다. 앱 600초 종료 기준 남은 시간이 220초 미만이면 건너뛴다(모델 150초 + 업로드 여유)
            from .adapters import inbox_digest
            result["inbox_digest"] = inbox_digest.collect(
                st, cfg, counts, paths=paths, exec_runner=exec_runner,
                process_started=started if process_started is None else min(process_started, started))
            if upload:
                if up is None:
                    up = (uploader_factory or Uploader)(cfg["server_url"], token,
                                                        timeout=cfg["upload"]["timeout_sec"])
                # 시간 예산은 이 실행의 시작부터 센다(수집 시간 포함). 예산으로 멈춰도(stopped time-budget) 뒤 단계는 그대로 돈다
                res_up = up.run(st, max_n=int(cfg["upload"]["max_per_run"]),
                                min_interval=float(cfg["upload"]["min_interval_sec"]),
                                budget=_budget_left(started, UPLOAD_BUDGET_SEC))
                if (res_up.get("stopped") or "").replace("-halted", "") == "policy":
                    # 허용 규칙이 바뀜 → 정책을 다시 받아 대기 요청을 고친 뒤 이번 실행에서 한 번만 다시 보낸다
                    ref = refresh_policy(paths, st, cfg, up)
                    result["policy_refresh"] = ref
                    if ref["status"] == "ok":
                        st.clear_halt("policy")
                        res_up = up.run(st, max_n=int(cfg["upload"]["max_per_run"]),
                                        min_interval=float(cfg["upload"]["min_interval_sec"]),
                                        budget=_budget_left(started, UPLOAD_BUDGET_SEC))
                result["upload"] = res_up
                if (res_up.get("stopped") or "").replace("-halted", "") not in _NO_WRITE_BACK_AFTER:
                    try:
                        wb = write_back(st, cfg, up, min_interval=float(cfg["upload"]["min_interval_sec"]))
                    except Exception:     # 되돌림의 뜻밖 오류가 이미 끝난 업로드 결과·종료 코드를 바꾸지 않게(값 없이 표시만)
                        wb = {"applied": 0, "skipped_not_pending": 0, "missing": 0, "retried": 0, "stopped": "error"}
                    if wb is not None:
                        result["write_back"] = wb
            result["state_resync"] = cfg["_resync"].finish()
            result["state"] = st.counts()
            return result
        finally:
            st.close()
    finally:
        lock.release()
