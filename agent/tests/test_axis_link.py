"""축 잇기(2026-11-18 명세 3절) — feed 축 코드 · 서버 기능(features) 알아내기 · 재업로드 · 축 한 장 어댑터. 전부 합성 자료.

- 서버가 axis_codes 를 알릴 때만 싣는다(옛 서버는 그 키를 CONTRACT-INVALID 로 거절하고, 거절된 판은 같은 내용으로 다시 만들지 않는다)
- 대기열이 비어도 하루 한 번 장치 정보를 물어 새 서버를 알아챈다 → 그 실행에서 재업로드가 시작된다
- 축 없는 글·버린 글은 투영이 그대로라 다시 올리지 않는다
- 한 장: <코드>.md 만, 내용 해시가 같으면 새 판 없음, 경로를 보내지 않음, URL·경로 가림, 옛 서버(변환 없음)면 만들지 않음
"""
from __future__ import annotations

import json
import os
import unittest

from agent import config as _config
from agent import contract, runner, store as _store
from agent.adapters import axis_pages, collected
from agent.contract import ContractError
from agent.tests.helpers import (FakeImportServer, TempHome, connected_config, keystore_with_secrets, write_jsonl)

ALL_TRANSFORMS = list(contract.TRANSFORMS)
OLD_TRANSFORMS = [t for t in ALL_TRANSFORMS if t != "axis-page/1"]


def row(i, **over):
    r = {"id": f"AXF{i:04d}", "author": f"가짜 작성자 {i}", "text": f"가짜 첫 줄 {i}\n가짜 본문 {i}",
         "post_url": f"https://example.invalid/axf/{i}", "status": "pending", "collected_at": "2026-11-12T09:30:00+0900",
         "source": "reddit", "axes_hint": ["C", "C-1"]}
    r.update(over)
    return r


class AxisCodesOfTest(unittest.TestCase):
    def test_rule_same_as_dashboard(self):
        f = collected.axis_codes_of
        self.assertEqual(f({"axes": ["B-1"], "axes_hint": ["C"]}), ["B-1"])          # 사람이 확정한 axes 먼저
        self.assertEqual(f({"axes": [], "axes_hint": ["C", "C-1"]}), ["C", "C-1"])    # 비면 axes_hint 전부
        self.assertEqual(f({"axes": None, "axes_hint": ["C"]}), ["C"])
        self.assertEqual(f({"axes_hint": ["C", " C ", "c", "TOO-LONG-CODE", 3, "D"]}), ["C", "D"])   # 꼴만·중복 제거
        self.assertEqual(f({"axes_hint": [f"X{i}" for i in range(15)]}), [f"X{i}" for i in range(10)])
        self.assertEqual(f({}), [])

    def test_adapter_keeps_fields_and_carries_codes(self):
        th = TempHome()
        try:
            p = os.path.join(th.root, "feed.jsonl")
            write_jsonl(p, [row(1), row(2, status="dropped"), row(3, axes_hint=[])])
            out = list(collected.FeedAdapter().collect({"enabled": True, "input_path": p,
                                                                "channels": {"reddit": "reddit"}}))
            self.assertEqual([o.axis_codes for o in out], [["C", "C-1"], [], []])   # 버린 글은 축을 싣지 않는다
            self.assertNotIn("axis_codes", out[0].fields)                            # 서버로 갈지는 runner 가 정한다
        finally:
            th.cleanup()


class ContractTest(unittest.TestCase):
    def base(self, **over):
        o = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": "is_" + "5a" * 12,
             "original_id": "o_" + "1" * 32, "revision": "v_" + "2" * 32, "previous_revision": None, "execution": "attended",
             "policy_revision": 1}
        o.update(over)
        return o

    def post(self, **over):
        return self.base(kind="collected_post", transform_version="collected-post/1", raw_id="0" * 48, channel="reddit",
                         collected_on="2026-11-12", title="가짜 첫 줄", state="pending", **over)

    def page(self, **over):
        o = self.base(kind="self_text", transform_version="axis-page/1", title="가짜 한 장", body="가짜 본문",
                      source_created_at="2026-11-18T14:00:00+09:00", axis_code="A")
        o.update(over)
        return {k: v for k, v in o.items() if v is not ...}

    def code(self, obj, code, field):
        with self.assertRaises(ContractError) as cm:
            contract.validate(obj)
        self.assertEqual((cm.exception.code, cm.exception.field), (code, field))

    def test_axis_codes(self):
        contract.validate(self.post(axis_codes=["A", "B-1"]))
        self.code(self.post(axis_codes=["a"]), "FORMAT", "axis_codes[0]")
        self.code(self.post(axis_codes=["A", "A"]), "DUPLICATE", "axis_codes")
        self.code(self.post(axis_codes=[f"X{i}" for i in range(11)]), "TOO-MANY", "axis_codes")
        # 정책 축(allowed_axes)과 대조하지 않는다 — 코드는 항목 id 가 아니다
        contract.validate(self.post(axis_codes=["A"]), policy={"source_instance_id": "is_" + "5a" * 12, "policy_revision": 1,
                                                               "allowed_axes": []})

    def test_axis_page(self):
        contract.validate(self.page())
        self.code(self.page(axis_code=...), "MISSING", "axis_code")
        self.code(self.page(axis_code="b-1"), "FORMAT", "axis_code")
        self.code(self.page(generation={"method": "none"}), "UNKNOWN-FIELD", "generation")
        self.code(self.page(transform_version="self-text/1"), "UNKNOWN-FIELD", "axis_code")
        self.code(self.page(body="본문 /Users/someone/x.md"), "BLOCKED-PATH", "body")   # 가림은 어댑터 몫


class _RunBase(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.ks = keystore_with_secrets()
        self.srv = FakeImportServer()
        self.feed = os.path.join(self.th.root, "feed.jsonl")
        cfg = connected_config(self.th, self.srv.url)
        cfg["allowed_actions"] = list(contract.ACTIONS)
        cfg["allowed_transforms"] = list(OLD_TRANSFORMS)
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed})
        self.cfg = cfg
        _config.save(self.th.paths, cfg)
        self.srv.device_info["policy"] = {"actions": list(contract.ACTIONS), "transform_versions": list(OLD_TRANSFORMS),
                                          "axes": []}

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def run_once(self, upload=True):
        return runner.run_once(self.th.paths, ks=self.ks, upload=upload)

    def sent(self, kind=None):
        out = [json.loads(b) for b in self.srv.bodies()]
        return [o for o in out if kind is None or o["kind"] == kind]

    def device_gets(self):
        return [c for c in self.srv.device_calls if c == ("GET", "/api/imports/device")]


class FeaturesAndReuploadTest(_RunBase):
    def test_old_server_never_gets_axis_codes(self):
        """옛 서버 = 장치 정보에 features 가 없다. 하루 한 번만 묻고, 축 코드를 싣지 않는다(옛 경로 그대로)."""
        write_jsonl(self.feed, [row(1), row(2)])
        res = self.run_once()
        self.assertEqual(res["features_refresh"], {"status": "ok", "features": []})
        self.assertEqual(len(self.device_gets()), 1)
        posts = self.sent("collected_post")
        self.assertEqual(len(posts), 2)
        self.assertTrue(all("axis_codes" not in p for p in posts))
        self.assertEqual(_config.load(self.th.paths)["server_features"], [])
        write_jsonl(self.feed, [row(1), row(2), row(3)])
        self.run_once()
        self.assertEqual(len(self.device_gets()), 1, "같은 날 두 번 묻지 않는다")
        self.assertTrue(all("axis_codes" not in p for p in self.sent("collected_post")))

    def test_new_server_empty_queue_starts_reupload(self):
        """옛 앱으로 다 올린 뒤(대기 0) 새 서버가 axis_codes 를 알리면, 다음 한 번의 실행에서 축 있는 글만 새 개정으로 다시 올라간다."""
        write_jsonl(self.feed, [row(1), row(2), row(3, axes_hint=[]), row(4, status="kept"), row(5, status="dropped")])
        self.run_once()                         # 옛 서버 — 축 없이 올림
        first = self.sent("collected_post")
        self.assertEqual(len(first), 4, "pending 3 + kept 1. 처음 보는 버린 글은 보내지 않는다")
        st = _store.Store(self.th.paths)
        self.assertEqual(len(st.pending_revisions()), 0)
        st.close()
        self.srv.requests.clear()
        # 새 서버 배포 + 원작자 축 항목 생성 → features axis_codes, 정책에 axis-page/1. 정책 판은 그대로(대기 0 이라 POLICY-STALE 없음)
        self.srv.device_info["features"] = ["axis_codes"]
        self.srv.device_info["policy"]["transform_versions"] = list(ALL_TRANSFORMS)
        st = _store.Store(self.th.paths)
        st.cursor_set(runner.FEATURES_CHECKED, "2000-01-01")   # 어제 물어본 것으로
        st.close()
        res = self.run_once()
        self.assertEqual(res["features_refresh"], {"status": "ok", "features": ["axis_codes"]})
        self.assertEqual(_config.load(self.th.paths)["server_features"], ["axis_codes"])
        again = self.sent("collected_post")
        self.assertEqual(sorted(tuple(p["axis_codes"]) for p in again), [("C", "C-1")] * 3)   # 축 있는 글 셋(pending 둘 + kept)
        self.assertTrue(all("axes" not in p and p["previous_revision"] for p in again))       # 새 개정, 옛 axes 경로 없음
        self.assertTrue(all(p["state"] != "removed" for p in again))                           # 버린 글은 다시 올리지 않는다
        self.srv.requests.clear()
        self.run_once()
        self.assertEqual(self.sent("collected_post"), [], "한 번 올린 뒤엔 같은 투영 — 다시 보내지 않는다")
        self.assertEqual(len(self.device_gets()), 2, "기능을 알면 더 묻지 않는다")

    def test_reupload_budget_per_run(self):
        """재업로드(이미 올린 글에 축을 처음 싣는 개정)는 실행당 몫만 — 앱의 run-once 시간 한도 안. 새 글은 몫과 무관."""
        write_jsonl(self.feed, [row(i) for i in range(1, 4)])
        self.run_once()                                       # 옛 서버 — 축 없이 3건
        self.srv.device_info["features"] = ["axis_codes"]
        st = _store.Store(self.th.paths)
        st.cursor_set(runner.FEATURES_CHECKED, "2000-01-01")
        st.close()
        write_jsonl(self.feed, [row(i) for i in range(1, 5)])  # 새 글 하나 더
        orig = runner.AXIS_RESTAGE_PER_RUN
        runner.AXIS_RESTAGE_PER_RUN = 2
        try:
            self.srv.requests.clear()
            res = self.run_once()
            got = self.sent("collected_post")
            self.assertEqual(len(got), 3)                     # 다시 올림 2 + 새 글 1
            self.assertEqual(sum(1 for p in got if p["previous_revision"] is None), 1)
            self.assertEqual(res["collect"]["deferred_axis"], 1)
            self.srv.requests.clear()
            self.run_once()
            self.assertEqual(len(self.sent("collected_post")), 1)   # 남은 1 은 다음 실행
            self.srv.requests.clear()
            self.run_once()
            self.assertEqual(self.sent("collected_post"), [])
        finally:
            runner.AXIS_RESTAGE_PER_RUN = orig

    def test_features_refresh_saved_on_policy_change_too(self):
        self.srv.device_info.update({"features": ["axis_codes", "future-x"], "policy_revision": 2})
        new = _config.apply_device_info(self.cfg, self.srv.device_info, expected_stream=self.cfg["source_instance_id"])
        self.assertEqual(new["server_features"], ["axis_codes"])          # 모르는 기능은 버린다
        del self.srv.device_info["features"]
        new = _config.apply_device_info(self.cfg, self.srv.device_info, expected_stream=self.cfg["source_instance_id"])
        self.assertEqual(new["server_features"], [])                      # 옛 서버 = 아는 기능 없음
        bad = dict(self.cfg, server_features=["nope"])
        with self.assertRaises(_config.ConfigError):
            _config.validate_config(bad)

    def test_upload_order_axis_pages_first(self):
        folder = os.path.join(self.th.root, "axis")
        os.makedirs(folder)
        with open(os.path.join(folder, "A.md"), "w", encoding="utf-8") as f:
            f.write("# A. 가짜 축 하나 — 나에 대해 한 장\n\n가짜 본문\n")
        self.srv.device_info["features"] = ["axis_codes"]
        self.srv.device_info["policy"]["transform_versions"] = list(ALL_TRANSFORMS)
        self.srv.device_info["policy_revision"] = 2       # 서버 이관(device-policy-all-v2)이 판을 올린다
        cfg = _config.load(self.th.paths)
        cfg["axis_pages"] = {"dir": folder}
        _config.save(self.th.paths, cfg)
        write_jsonl(self.feed, [row(i) for i in range(1, 6)])
        res = self.run_once()
        self.assertEqual(res["policy_refresh_before"]["status"], "ok")   # 변환이 빠져 있어 수집 전에 다시 받음
        kinds = [o["transform_version"] for o in self.sent()]
        self.assertEqual(kinds[0], "axis-page/1", kinds)                          # 수집 글 재업로드 뒤에 줄 서지 않는다


class AxisPagesTest(_RunBase):
    def setUp(self):
        super().setUp()
        self.dir = os.path.join(self.th.root, "axis")
        os.makedirs(self.dir)
        cfg = _config.load(self.th.paths)
        cfg["axis_pages"] = {"dir": self.dir}
        cfg["allowed_transforms"] = list(ALL_TRANSFORMS)
        cfg["adapters"]["feed"]["enabled"] = False
        _config.save(self.th.paths, cfg)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def pages(self):
        return self.sent("self_text")

    def test_files_parse_mask_and_no_path(self):
        self.write("A.md", "# A. 가짜 축 하나 — 나에 대해 한 장\n\n## 가짜 절\n본문 https://example.invalid/x 와 "
                           "/Users/someone/secret/note.md 그리고 someone@example.invalid\n")
        self.write("B-1.md", "머리 줄 없는 가짜 본문\n")
        for junk in ("A.prev.md", "A.bad.json", "A.error.txt", "A.material.json", "lower.md", "TOO-LONG-CODE.md", ".A.md"):
            self.write(junk, "# 가짜\n읽으면 안 되는 본문\n")
        os.symlink(os.path.join(self.dir, "A.md"), os.path.join(self.dir, "C.md"))
        res = self.run_once()
        self.assertEqual(res["axis_pages"]["files"], 2)
        self.assertEqual(res["axis_pages"]["redacted"], 3)
        got = {p["axis_code"]: p for p in self.pages()}
        self.assertEqual(sorted(got), ["A", "B-1"])
        a = got["A"]
        self.assertEqual(a["transform_version"], "axis-page/1")
        self.assertEqual(a["title"], "A. 가짜 축 하나 — 나에 대해 한 장")
        self.assertTrue(a["body"].startswith("## 가짜 절"))
        for m in ("‹링크›", "‹경로›", "‹메일›"):
            self.assertIn(m, a["body"])
        self.assertRegex(a["source_created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")
        self.assertEqual(got["B-1"]["title"], "축 B-1 한 장")
        blob = b"\n".join(self.srv.bodies())
        self.assertNotIn(self.dir.encode("utf-8"), blob)
        self.assertNotIn("읽으면 안 되는".encode("utf-8"), blob)
        st = _store.Store(self.th.paths)
        keys = sorted(r[0] for r in st.conn.execute("SELECT dedupe_key FROM events WHERE adapter='axis-pages'").fetchall())
        st.close()
        self.assertEqual(keys, ["axis-page:A", "axis-page:B-1"])   # 경로 없는 중복 기준

    def test_same_content_no_new_page_and_new_content_is_revision(self):
        self.write("A.md", "# 가짜\n첫 판\n")
        self.run_once()
        first = self.pages()
        self.assertEqual(len(first), 1)
        self.srv.requests.clear()
        p = os.path.join(self.dir, "A.md")
        os.utime(p, (os.stat(p).st_atime, os.stat(p).st_mtime + 3600))     # 수정 시각만 바뀐 재작성
        res = self.run_once()
        self.assertEqual(self.pages(), [])
        self.assertEqual(res["axis_pages"]["unchanged"], 1)
        self.write("A.md", "# 가짜\n둘째 판\n")
        self.run_once()
        second = self.pages()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["original_id"], first[0]["original_id"])       # 같은 축 = 같은 원본의 새 개정
        self.assertEqual(second[0]["previous_revision"], first[0]["revision"])

    def test_old_server_or_disabled_makes_nothing(self):
        self.write("A.md", "# 가짜\n본문\n")
        cfg = _config.load(self.th.paths)
        cfg["allowed_transforms"] = list(OLD_TRANSFORMS)
        _config.save(self.th.paths, cfg)
        res = self.run_once()
        self.assertEqual(res["axis_pages"]["skipped"], "policy")
        self.assertEqual(self.pages(), [])
        cfg["axis_pages"] = {"dir": None}
        _config.save(self.th.paths, cfg)
        self.assertEqual(self.run_once()["axis_pages"]["skipped"], "disabled")
        cfg["axis_pages"] = {"dir": "relative/axis"}
        with self.assertRaises(_config.ConfigError):
            _config.save(self.th.paths, cfg)


if __name__ == "__main__":
    unittest.main()
