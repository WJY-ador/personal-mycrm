"""수집 글(collected-post/1) — 계약 · feed·reactions·mail 어댑터 변환 · 전송 대기(업로드 없이). 전부 합성 자료."""
from __future__ import annotations

import copy
import json
import os
import unittest

from agent import adapters, config as _config, contract, runner, store as _store
from agent.adapters import CollectedPost, Observation, Quarantine
from agent.adapters import collected as C
from agent.contract import ContractError
from agent.tests.helpers import FakeImportServer, TempHome, connected_config, keystore_with_secrets, write_jsonl

SID = "is_5a5a5a5a5a5a5a5a5a5a5a5a"
AX1, AX2 = "i_AxisAAAA", "i_AxisBBBB"
BODY_MARK = "SYNTH-BODY-SECOND-LINE"


def post(**over):
    o = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": SID, "original_id": "o_" + "1" * 32,
         "revision": "v_" + "2" * 32, "previous_revision": None, "kind": "collected_post", "execution": "attended",
         "transform_version": "collected-post/1", "policy_revision": 1, "raw_id": "0" * 48, "channel": "linkedin",
         "collected_on": "2026-11-12", "title": "합성 첫 줄", "state": "pending"}
    o.update(over)
    return o


def feed_row(i, **over):
    r = {"id": f"FEED{i:04d}", "author": f"합성 작성자 {i}", "author_desc": "SYNTH-AUTHOR-DESC",
         "text": f"합성 첫 줄 {i}\n{BODY_MARK} {i} 본문 둘째 줄", "post_url": f"https://example.invalid/feed/{i}",
         "status": "pending", "collected_at": "2026-11-12T09:30:00+0900", "published_at": "2026-11-11T16:00:00Z",
         "source": "reddit", "axes": ["AXCODE1", "AXCODE9"], "grade": "signal", "summary": "합성 AI 요약",
         "long": {"asis": "합성 asis", "tobe": "합성 tobe", "ops": "합성 ops", "points": ["점 하나", "점 둘"]}}
    r.update(over)
    return r


class ContractCollectedTest(unittest.TestCase):
    def code(self, obj, code, field=None):
        with self.assertRaises(ContractError) as cm:
            contract.validate(obj)
        self.assertEqual(cm.exception.code, code)
        if field is not None:
            self.assertEqual(cm.exception.field, field)

    def test_minimal_and_full_valid(self):
        contract.validate(post())
        full = post(post_url="https://example.invalid/p/1?x=1", author_display="합성 이름", posted_on="2026-11-10",
                    axes=[AX1], ai={"grade": "news", "summary": "s", "as_is": "a", "to_be": "b", "ops": "c",
                                    "points": ["p"] * 12})
        contract.encode_request(full)

    def test_required_and_enums(self):
        for k in ("raw_id", "channel", "collected_on", "title", "state"):
            o = post()
            del o[k]
            self.code(o, "MISSING", k)
        self.code(post(channel="facebook"), "ENUM", "channel")
        self.code(post(state="dropped"), "ENUM", "state")
        self.code(post(collected_on="2026-11-12T00:00:00Z"), "DATE", "collected_on")
        self.code(post(raw_id="x"), "FORMAT", "raw_id")
        self.code(post(body="본문"), "UNKNOWN-FIELD", "body")
        self.code(post(transform_version="board-likes/1"), "TRANSFORM-KIND")

    def test_title_rules(self):
        contract.validate(post(title="가" * 200))
        self.code(post(title="가" * 201), "TOO-LONG", "title")
        self.code(post(title="줄\n바꿈"), "SINGLE-LINE", "title")
        self.code(post(title="  "), "EMPTY", "title")

    def test_post_url_is_only_url_field(self):
        u = "https://example.invalid/p/1"
        contract.validate(post(post_url=u))
        self.code(post(post_url="http://example.invalid/p/1"), "FORMAT", "post_url")
        self.code(post(post_url="https://" + "a" * 2000), "TOO-LONG", "post_url")
        self.code(post(post_url="https://"), "FORMAT", "post_url")
        self.code(post(post_url="https://example.invalid/a b"), "SINGLE-LINE", "post_url")
        self.code(post(post_url=5), "TYPE", "post_url")
        contract.validate(post(post_url=None, posted_on=None, author_display=None, ai={}))   # 서버처럼 null = 없음
        # 같은 URL 이 다른 필드에 있으면 그대로 거절
        self.code(post(title="보기 " + u), "BLOCKED-URL", "title")
        self.code(post(author_display=u), "BLOCKED-URL", "author_display")
        self.code(post(ai={"summary": "보기 " + u}), "BLOCKED-URL", "ai.summary")
        # post_url 에도 이메일·경로 꼴은 거절
        self.code(post(post_url="https://example.invalid/?m=someone@example.invalid"), "BLOCKED-EMAIL", "post_url")
        self.code(post(post_url="https://example.invalid/ /" + "Users/someone"), "SINGLE-LINE", "post_url")

    def test_ai_rules(self):
        self.code(post(ai="요약"), "TYPE", "ai")
        self.code(post(ai={"points": [" "]}), "EMPTY", "ai.points[0]")
        self.code(post(ai={"grade": "great"}), "ENUM", "ai.grade")
        self.code(post(ai={"summary": "가" * 501}), "TOO-LONG", "ai.summary")
        self.code(post(ai={"ops": "가" * 1001}), "TOO-LONG", "ai.ops")
        self.code(post(ai={"points": ["p"] * 13}), "TOO-MANY", "ai.points")
        self.code(post(ai={"points": ["가" * 301]}), "TOO-LONG", "ai.points[0]")
        self.code(post(ai={"body": "x"}), "UNKNOWN-FIELD", "ai.body")

    def test_axes_and_policy(self):
        self.code(post(axes=[AX1, AX1]), "DUPLICATE", "axes")
        pol = {"source_instance_id": SID, "policy_revision": 1, "allowed_axes": [AX1]}
        contract.validate(post(axes=[AX1]), policy=pol)
        with self.assertRaises(ContractError) as cm:
            contract.validate(post(axes=[AX2]), policy=pol)
        self.assertEqual(cm.exception.code, "POLICY-AXIS")
        with self.assertRaises(ContractError) as cm:
            contract.validate(post(), policy=dict(pol, transforms=["board-likes/1"]))
        self.assertEqual(cm.exception.code, "POLICY-TRANSFORM")

    def test_new_activity_transforms(self):
        base = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": SID,
                "original_id": "o_" + "1" * 32, "revision": "v_" + "2" * 32, "previous_revision": None,
                "kind": "activity", "execution": "attended", "policy_revision": 1, "state": "active",
                "occurred_on": None, "observed_on": "2026-11-12", "raw_id": "0" * 48, "people": [], "axes": []}
        contract.validate(dict(base, transform_version="board-feed/1", action="save", provider="kakao"))
        contract.validate(dict(base, transform_version="board-reactions/1", action="comment", provider="sns"))
        contract.validate(dict(base, transform_version="board-mail/1", action="send", provider="mail"))
        self.code(dict(base, transform_version="board-feed/1", action="read", provider="sns"), "NOT-IN-TRANSFORM",
                  "action")
        self.code(dict(base, transform_version="board-mail/1", action="read", provider="sns"), "NOT-IN-TRANSFORM",
                  "provider")


class HelpersTest(unittest.TestCase):
    def test_kst_date(self):
        self.assertEqual(C.kst_date("2026-11-12"), "2026-11-12")
        self.assertEqual(C.kst_date("2026-11-12T23:59:00+0900"), "2026-11-12")
        self.assertEqual(C.kst_date("2026-11-12T14:59:59.123Z"), "2026-11-12")
        self.assertEqual(C.kst_date("2026-11-12T15:00:00.000Z"), "2026-11-13")   # UTC 15시 = KST 다음 날 0시
        self.assertEqual(C.kst_date("2026-11-12T20:00:00-05:00"), "2026-11-13")
        self.assertIsNone(C.kst_date("2026-11-12T10:00:00"))                     # 시간대 모름 → 쓰지 않음
        self.assertIsNone(C.kst_date("2026-02-30"))
        self.assertIsNone(C.kst_date(None))
        self.assertEqual(C.kst_date(1762966800), "2025-11-13")                   # 초 epoch (2025-11-12T17:00Z)
        self.assertEqual(C.kst_date(1762966800000), "2025-11-13")                # 밀리초 epoch
        self.assertIsNone(C.kst_date(True))

    def test_title(self):
        self.assertEqual(C.title_of("\n\n  첫 줄  \n둘째"), "첫 줄")
        self.assertEqual(C.title_of("가" * 300), "가" * 200)
        self.assertEqual(C.title_of("링크 https://example.invalid/a?b=1 참고"), "링크 ‹링크› 참고")
        self.assertEqual(C.title_of("메일 someone@example.invalid 로"), "메일 ‹메일› 로")
        self.assertEqual(C.title_of("파일 ~" + "/Documents/x.md 봐"), "파일 ‹경로› 봐")
        self.assertIsNone(C.title_of(""))
        self.assertIsNone(C.title_of(None))

    def test_axes_map(self):
        self.assertEqual(C.map_axes(["A", "X", "B", "A"], {"A": AX1, "B": AX2}), [AX1, AX2])
        self.assertEqual(C.map_axes("A", {"A": AX1}), [])


class FeedAdapterTest(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.path = os.path.join(self.th.root, "feed.jsonl")

    def tearDown(self):
        self.th.cleanup()

    def section(self, **over):
        s = copy.deepcopy(_config.default_config()["adapters"]["feed"])
        s.update({"enabled": True, "input_path": self.path, "axes_map": {"AXCODE1": AX1}})
        s.update(over)
        return s

    def collect(self, rows, **over):
        write_jsonl(self.path, rows)
        return list(adapters.get("feed").collect(self.section(**over)))

    def test_pending_row(self):
        out = self.collect([feed_row(1)])
        self.assertEqual(len(out), 1)
        cp = out[0]
        self.assertIsInstance(cp, CollectedPost)
        self.assertEqual(cp.fields, {
            "channel": "reddit", "collected_on": "2026-11-12", "title": "합성 첫 줄 1", "state": "pending",
            "post_url": "https://example.invalid/feed/1", "author_display": "합성 작성자 1", "posted_on": "2026-11-12",
            "axes": [AX1], "ai": {"grade": "signal", "summary": "합성 AI 요약", "as_is": "합성 asis",
                                  "to_be": "합성 tobe", "ops": "합성 ops", "points": ["점 하나", "점 둘"]}})
        self.assertFalse(cp.only_if_sent)
        self.assertEqual(cp.raw["text"], feed_row(1)["text"])     # 원문은 PC 원문 저장소로

    def test_kept_adds_save_activity(self):
        out = self.collect([feed_row(1, status="kept", source="kakao")])
        cp, act = out
        self.assertEqual(cp.fields["state"], "kept")
        self.assertEqual(cp.fields["channel"], "kakao")
        self.assertIsInstance(act, Observation)
        self.assertEqual((act.action, act.state, act.provider), ("save", "active", "kakao"))
        self.assertIsNone(act.occurred_on)            # 보관 시각 필드가 없다 — 수집 시각으로 대신하지 않는다
        self.assertEqual(act.observed_on, "2026-11-12")
        self.assertEqual(act.axes, [AX1])
        self.assertEqual(act.people, [])

    def test_removed_statuses_and_unknown(self):
        out = self.collect([feed_row(i, status=s) for i, s in
                            enumerate(("dropped", "expired", "excluded", "superseded"), 1)])
        self.assertTrue(all(isinstance(o, CollectedPost) and o.only_if_sent and o.fields["state"] == "removed"
                            for o in out))
        out = self.collect([feed_row(1, status="weird"), feed_row(2, status=None)])
        self.assertEqual([o.reason for o in out], ["unknown-status", "unknown-status"])
        # 버린 글은 형식 오류여도 격리하지 않는다
        self.assertEqual(self.collect([feed_row(1, status="dropped", text="")]), [])

    def test_channel_mapping(self):
        row = feed_row(1)
        del row["source"]
        rows = [row, feed_row(2, source="linkedin_search"), feed_row(3, source="brunch"),
                feed_row(4, source="naver_blog"), feed_row(5, source="unknown_src")]
        out = self.collect(rows)
        self.assertEqual([o.fields["channel"] for o in out[:4]], ["linkedin", "linkedin", "blog", "blog"])
        self.assertEqual(out[4].reason, "unmapped-channel")
        out = self.collect([feed_row(1, source="reddit")], channels={"reddit": None})
        self.assertEqual(out[0].reason, "unmapped-channel")

    def test_optional_fields_omitted(self):
        r = feed_row(1, post_url="http://insecure.invalid/x", author="", published_at=None, axes=["NOPE"],
                     grade="great", summary="", long=None)
        cp = self.collect([r])[0]
        self.assertEqual(set(cp.fields), {"channel", "collected_on", "title", "state"})

    def test_ai_truncated_and_masked(self):
        r = feed_row(1, summary="가" * 600 + " https://example.invalid/x",
                     long={"points": ["p"] * 20, "asis": "메일 someone@example.invalid"})
        ai = self.collect([r])[0].fields["ai"]
        self.assertEqual(len(ai["summary"]), 500)
        self.assertEqual(len(ai["points"]), 12)
        self.assertEqual(ai["as_is"], "메일 ‹메일›")

    def test_missing_fields_quarantined(self):
        out = self.collect([feed_row(1, id=""), feed_row(2, collected_at="2026-11-12T09:00:00"),
                            feed_row(3, text="   \n"), "{bad"])
        self.assertEqual(sorted(o.reason for o in out), ["bad-json", "no-collected-date", "no-event-id", "no-title"])

    def test_duplicates(self):
        out = self.collect([feed_row(1), feed_row(1, status="kept")])
        self.assertEqual([type(o).__name__ for o in out], ["CollectedPost", "Observation"])   # 마지막 행
        # URL 은 신원이 아니다 — 같은 ID 에 URL 이 바뀌면 마지막 행(새 개정으로 갱신)
        out = self.collect([feed_row(1), feed_row(1, post_url="https://example.invalid/other")])
        self.assertEqual(out[0].fields["post_url"], "https://example.invalid/other")

    def test_config_required(self):
        with self.assertRaises(adapters.AdapterError):
            adapters.get("feed").check_config(self.section(input_path="relative.jsonl"))
        with self.assertRaises(adapters.AdapterError):
            adapters.get("feed").check_config(self.section(channels={"x": "facebook"}))


class ReactionsAdapterTest(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.rpath = os.path.join(self.th.root, "reactions.jsonl")
        self.lpath = os.path.join(self.th.root, "threads-likes.jsonl")

    def tearDown(self):
        self.th.cleanup()

    def section(self):
        s = copy.deepcopy(_config.default_config()["adapters"]["reactions"])
        s.update({"enabled": True, "inputs": [
            {"path": self.rpath, "format": "reactions", "channel": "linkedin"},
            {"path": self.lpath, "format": "threads_likes", "channel": "threads"}]})
        return s

    def test_both_formats(self):
        write_jsonl(self.rpath, [
            {"id": "R1", "author": "합성 반응 작성자", "text": "반응 첫 줄\n" + BODY_MARK, "post_url": "https://example.invalid/r/1",
             "posted_at": "2026-11-10T01:00:00Z", "collected_at": "2026-11-12T08:00:00+0900",
             "reacted_at": "2026-11-11T16:30:00Z", "kind": "comment"},
            {"id": "R1", "author": "합성 반응 작성자", "text": "반응 첫 줄\n" + BODY_MARK, "post_url": "https://example.invalid/r/1",
             "posted_at": "2026-11-10T01:00:00Z", "collected_at": "2026-11-12T08:00:00+0900",
             "reacted_at": "2026-11-11T10:00:00Z", "kind": "like"},
            {"id": "R2", "author": "x", "text": "둘째 글", "post_url": "https://example.invalid/r/2",
             "collected_at": "2026-11-12T08:00:00+0900", "kind": "bookmark"},
        ])
        write_jsonl(self.lpath, [
            {"id": "T1", "author": "synth_handle", "text": "스레드 첫 줄\n" + BODY_MARK,
             "original_url": "https://example.invalid/@synth_handle/post/T1", "posted_at": "2026-11-09T23:30:00.000Z",
             "first_seen": "2026-11-12"},
        ])
        out = list(adapters.get("reactions").collect(self.section()))
        posts = [o for o in out if isinstance(o, CollectedPost)]
        acts = [o for o in out if isinstance(o, Observation)]
        quar = [o for o in out if isinstance(o, Quarantine)]
        self.assertEqual(len(posts), 3)
        r1 = posts[0].fields
        self.assertEqual(r1, {"channel": "linkedin", "collected_on": "2026-11-12", "title": "반응 첫 줄",
                              "state": "kept", "post_url": "https://example.invalid/r/1",
                              "author_display": "합성 반응 작성자", "posted_on": "2026-11-10"})
        self.assertEqual([(a.action, a.occurred_on, a.provider) for a in acts if a.dedupe_key.startswith("reactions:R1")],
                         [("comment", "2026-11-12", "sns"), ("like", "2026-11-11", "sns")])
        self.assertEqual([q.reason for q in quar], ["unmapped-kind"])
        t1 = posts[2].fields
        self.assertEqual((t1["channel"], t1["collected_on"], t1["posted_on"], t1["post_url"]),
                         ("threads", "2026-11-12", "2026-11-10", "https://example.invalid/@synth_handle/post/T1"))
        # Threads 좋아요 꼴은 수집 글만 — like 활동은 likes 어댑터 몫
        self.assertEqual([a for a in acts if a.dedupe_key.startswith("threads_likes:")], [])

    def test_config(self):
        a = adapters.get("reactions")
        s = self.section()
        s["inputs"][0]["format"] = "csv"
        with self.assertRaises(adapters.AdapterError):
            a.check_config(s)
        with self.assertRaises(adapters.AdapterError):
            a.check_config({"enabled": True, "inputs": []})
        s = self.section()
        s["inputs"][0]["channel"] = "kakao"          # 서버 board-reactions/1 provider 에 kakao 없음
        with self.assertRaises(adapters.AdapterError):
            a.check_config(s)
        # 같은 Threads 좋아요 파일을 likes 와 reactions 가 함께 읽어도 설정 오류가 아니다(활동이 겹치지 않는다)
        cfg = _config.default_config()
        cfg["adapters"]["likes"].update({"enabled": True, "input_path": self.lpath})
        cfg["adapters"]["reactions"].update({"enabled": True, "inputs": [
            {"path": self.lpath, "format": "threads_likes", "channel": "threads"}]})
        _config.validate_config(cfg)


class MailAdapterTest(unittest.TestCase):
    def test_explicit_actions_only(self):
        th = TempHome()
        try:
            path = os.path.join(th.root, "mail.jsonl")
            base = {"subject": "SYNTH-SUBJECT", "snippet": "SYNTH-SNIPPET", "from_name": "SYNTH-FROM",
                    "from_email": "sender@example.invalid", "acct": "me@example.invalid",
                    "ts": "2026-11-12T01:00:00Z", "first_seen": "2026-11-12"}
            write_jsonl(path, [
                dict(base, url="https://mail.example.invalid/m/1", unread=True),             # 받기만 함 → 없음
                dict(base, url="https://mail.example.invalid/m/2", unread=False),            # 읽음
                dict(base, url="https://mail.example.invalid/m/3", sent=True, saved=True),   # 발송 + 보관
                dict(base, url="https://mail.example.invalid/m/4"),                          # unread 없음 → 없음
            ])
            out = list(adapters.get("mail").collect({"enabled": True, "input_path": path}))
            self.assertTrue(all(isinstance(o, Observation) for o in out))
            self.assertEqual([(o.action, o.occurred_on, o.provider) for o in out],
                             [("read", None, "mail"), ("save", None, "mail"), ("send", "2026-11-12", "mail")])
            for o in out:
                self.assertNotIn("@", o.dedupe_key)
                self.assertNotIn("example", o.dedupe_key)
        finally:
            th.cleanup()


class StagingCollectedTest(unittest.TestCase):
    """수집 → 변환 → 계약 → 전송 대기(업로드 없이)."""

    def setUp(self):
        self.th = TempHome()
        self.feed = os.path.join(self.th.root, "feed.jsonl")
        self.mail = os.path.join(self.th.root, "mail.jsonl")
        self.ks = keystore_with_secrets()
        cfg = connected_config(self.th, "http://127.0.0.1:9")
        cfg["allowed_axes"] = [AX1]
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed, "axes_map": {"AXCODE1": AX1}})
        cfg["adapters"]["mail"].update({"enabled": True, "input_path": self.mail})
        _config.save(self.th.paths, cfg)
        write_jsonl(self.mail, [])

    def tearDown(self):
        self.th.cleanup()

    def run_stage(self):
        return runner.run_once(self.th.paths, ks=self.ks, upload=False)

    def bodies(self):
        out = []
        for n in sorted(os.listdir(self.th.paths.pending)):
            with open(os.path.join(self.th.paths.pending, n), "rb") as f:
                out.append(f.read())
        return out

    def accept_all(self):
        st = _store.Store(self.th.paths)
        for r in st.pending_revisions():
            st.mark(r["idempotency_key"], "accepted", result={"import_id": "ie_x", "state": "applied"})
        st.close()

    def test_body_and_private_fields_not_in_payload(self):
        write_jsonl(self.feed, [feed_row(1), feed_row(2, status="kept")])
        write_jsonl(self.mail, [{"subject": "SYNTH-SUBJECT", "snippet": "SYNTH-SNIPPET", "from_name": "SYNTH-FROM",
                                 "from_email": "sender@example.invalid", "url": "https://mail.example.invalid/m/1",
                                 "acct": "me@example.invalid", "ts": "2026-11-12T01:00:00Z",
                                 "first_seen": "2026-11-12", "unread": False}])
        res = self.run_stage()
        self.assertEqual(res["collect"]["staged"], 4)       # 수집 글 2 + save 1 + read 1
        blob = b"\n".join(self.bodies())
        for leak in (BODY_MARK, "SYNTH-AUTHOR-DESC", "AXCODE", "SYNTH-SUBJECT", "SYNTH-SNIPPET", "SYNTH-FROM",
                     "sender@", "me@", "mail.example.invalid", "FEED0001"):
            self.assertNotIn(leak.encode("utf-8"), blob, leak)
        objs = [json.loads(b) for b in self.bodies()]
        kinds = sorted((o["kind"], o["transform_version"]) for o in objs)
        self.assertEqual(kinds, [("activity", "board-feed/1"), ("activity", "board-mail/1"),
                                 ("collected_post", "collected-post/1"), ("collected_post", "collected-post/1")])
        st = _store.Store(self.th.paths)
        try:
            for o in objs:
                if o["kind"] == "collected_post":
                    with open(st.resolve_raw_path(o["raw_id"]), encoding="utf-8") as f:
                        self.assertIn(BODY_MARK, json.load(f)["text"])     # 원문은 PC 원문 저장소(raw_id)에
        finally:
            st.close()

    def test_same_raw_id_on_update_and_removed(self):
        write_jsonl(self.feed, [feed_row(1, summary=None, long=None, grade=None)])
        self.run_stage()
        first = json.loads(self.bodies()[0])
        self.assertNotIn("ai", first)
        self.accept_all()
        self.assertEqual(self.run_stage()["collect"]["unchanged"], 1)
        # 요약이 나중에 채워짐 → 같은 raw_id·original_id 의 새 개정
        write_jsonl(self.feed, [feed_row(1)])
        self.assertEqual(self.run_stage()["collect"]["staged"], 1)
        second = json.loads(self.bodies()[0])
        self.assertEqual((second["raw_id"], second["original_id"]), (first["raw_id"], first["original_id"]))
        self.assertEqual(second["previous_revision"], first["revision"])
        self.assertEqual(second["ai"]["summary"], "합성 AI 요약")
        self.accept_all()
        # 이미 올린 글이 버림 → removed. 처음 보는 버린 글은 올리지 않는다
        write_jsonl(self.feed, [feed_row(1, status="dropped"), feed_row(2, status="expired")])
        res = self.run_stage()
        self.assertEqual((res["collect"]["staged"], res["collect"]["not_sent"]), (1, 1))
        third = json.loads(self.bodies()[0])
        self.assertEqual((third["state"], third["raw_id"]), ("removed", first["raw_id"]))

    def test_masked_count_and_mask_only_title(self):
        write_jsonl(self.feed, [
            feed_row(1, text="보기 https://example.invalid/a 와 someone@example.invalid\n본문",
                     summary="요약 https://example.invalid/b", long=None),
            feed_row(2, text="https://example.invalid/only\n본문"),       # 가린 뒤 표시만 남는 제목 → 격리
        ])
        res = self.run_stage()
        c = res["collect"]
        self.assertEqual((c["staged"], c["masked"], c["quarantined"]), (1, 3, 1))
        o = json.loads(self.bodies()[0])
        self.assertEqual(o["title"], "보기 ‹링크› 와 ‹메일›")
        self.assertEqual(o["ai"]["summary"], "요약 ‹링크›")

    def test_axes_map_outside_policy_rejected(self):
        cfg = _config.load(self.th.paths)
        cfg["adapters"]["feed"]["axes_map"] = {"AXCODE1": AX2}
        with self.assertRaises(_config.ConfigError):
            _config.save(self.th.paths, cfg)


class UploadObjectMissingTest(unittest.TestCase):
    """503 OBJECT-MISSING — 그 개정만 지수 대기, 이번 실행의 남은 수집 글은 미루고 활동은 계속 보낸다."""

    def test_object_missing_defers_only_collected(self):
        srv, th = FakeImportServer(), TempHome()
        try:
            feed, mail = os.path.join(th.root, "feed.jsonl"), os.path.join(th.root, "mail.jsonl")
            write_jsonl(feed, [feed_row(i) for i in range(1, 4)])
            write_jsonl(mail, [{"url": "https://mail.example.invalid/m/1", "unread": False,
                                "first_seen": "2026-11-12"}])
            cfg = connected_config(th, srv.url)
            cfg["adapters"]["feed"].update({"enabled": True, "input_path": feed})
            cfg["adapters"]["mail"].update({"enabled": True, "input_path": mail})
            _config.save(th.paths, cfg)
            srv.script = [(503, {"code": "OBJECT-MISSING"})]
            res = runner.run_once(th.paths, ks=keystore_with_secrets())
            up = res["upload"]
            self.assertEqual((up["sent"], up["accepted"], up["deferred"], up["stopped"]), (2, 1, 3, None))
            kinds = [json.loads(b)["kind"] for _, b in srv.requests]
            self.assertEqual(kinds, ["collected_post", "activity"])
            st = _store.Store(th.paths)
            try:
                self.assertEqual(st.counts()["pending"], 3)              # 수집 글 셋은 대기 유지(rejected 아님)
            finally:
                st.close()
            res = runner.run_once(th.paths, ks=keystore_with_secrets())    # 오브젝트가 생김 → 미룬 둘이 간다
            self.assertEqual(res["upload"]["accepted"], 2)
        finally:
            srv.close()
            th.cleanup()


class PolicyFilledTest(unittest.TestCase):
    """실제 장치처럼 허용 규칙이 채워진 설정 — 허용 밖이면 격리, 웹에서 켜면 수집 전에 다시 받아 보낸다."""

    def test_policy_refresh_before_collect(self):
        srv, th = FakeImportServer(), TempHome()
        try:
            feed = os.path.join(th.root, "feed.jsonl")
            write_jsonl(feed, [feed_row(1, status="kept")])
            cfg = connected_config(th, srv.url)
            cfg.update({"allowed_actions": ["like"], "allowed_transforms": ["board-likes/1"]})
            cfg["adapters"]["feed"].update({"enabled": True, "input_path": feed})
            _config.save(th.paths, cfg)
            # 서버도 아직 그대로(판 1) → 다시 받아도 같음 → 만들지 않고 건너뜀(격리 아님), 전송 없음
            res = runner.run_once(th.paths, ks=keystore_with_secrets())
            self.assertEqual(res["policy_refresh_before"]["status"], "unchanged")
            c = res["collect"]
            self.assertEqual((c["staged"], c["quarantined"], c["skipped_policy"]), (0, 0, 2))
            self.assertEqual(srv.requests, [])
            # 웹에서 허용을 켬(판 2) → 수집 전에 받아 그 판으로 만든다
            srv.device_info = dict(srv.device_info, policy_revision=2, policy={
                "actions": ["like", "save"], "axes": [],
                "transform_versions": ["board-likes/1", "board-feed/1", "collected-post/1"]})
            res = runner.run_once(th.paths, ks=keystore_with_secrets())
            self.assertEqual(res["policy_refresh_before"]["status"], "ok")
            self.assertEqual(res["collect"]["staged"], 2)
            self.assertEqual(res["upload"]["accepted"], 2)
            self.assertTrue(all(json.loads(b)["policy_revision"] == 2 for _, b in srv.requests))
            # 허용이 다 있으면 다시 묻지 않는다
            n = len(srv.device_calls)
            res = runner.run_once(th.paths, ks=keystore_with_secrets())
            self.assertNotIn("policy_refresh_before", res)
            self.assertEqual(len(srv.device_calls), n)
        finally:
            srv.close()
            th.cleanup()


class ReactionsStagingTest(unittest.TestCase):
    def test_both_formats_staged_without_body(self):
        th = TempHome()
        try:
            rp, lp = os.path.join(th.root, "r.jsonl"), os.path.join(th.root, "l.jsonl")
            write_jsonl(rp, [{"id": "R1", "author": "합성", "text": "반응 첫 줄\n" + BODY_MARK,
                              "post_url": "https://example.invalid/r/1", "collected_at": "2026-11-12",
                              "reacted_at": "2026-11-11T10:00:00Z", "kind": "repost"}])
            write_jsonl(lp, [{"id": "T1", "author": "synth_handle", "text": "스레드 첫 줄\n" + BODY_MARK,
                              "original_url": "https://example.invalid/t/1", "first_seen": "2026-11-12"}])
            cfg = connected_config(th, "http://127.0.0.1:9")
            cfg["adapters"]["reactions"].update({"enabled": True, "inputs": [
                {"path": rp, "format": "reactions", "channel": "web"},
                {"path": lp, "format": "threads_likes", "channel": "threads"}]})
            _config.save(th.paths, cfg)
            res = runner.run_once(th.paths, ks=keystore_with_secrets(), upload=False)
            self.assertEqual(res["collect"]["staged"], 3)        # 수집 글 2 + repost 1
            objs, blob = [], b""
            for n in sorted(os.listdir(th.paths.pending)):
                with open(os.path.join(th.paths.pending, n), "rb") as f:
                    b = f.read()
                blob += b
                objs.append(json.loads(b))
            self.assertNotIn(BODY_MARK.encode(), blob)
            self.assertNotIn(b"R1", blob)
            acts = sorted((o["action"], o["provider"], o["transform_version"]) for o in objs if o["kind"] == "activity")
            self.assertEqual(acts, [("repost", "web", "board-reactions/1")])
        finally:
            th.cleanup()


class ConfigCollectedTest(unittest.TestCase):
    def test_defaults_off_and_kakao_note(self):
        cfg = _config.default_config()
        for n in ("feed", "reactions", "mail", "kakao"):
            self.assertFalse(cfg["adapters"][n]["enabled"])
        self.assertIn("feed", cfg["adapters"]["kakao"]["note"])
        _config.validate_config(cfg)
        with self.assertRaises(adapters.AdapterNotActive):
            adapters.get("kakao").check_config({"enabled": True})


if __name__ == "__main__":
    unittest.main()
