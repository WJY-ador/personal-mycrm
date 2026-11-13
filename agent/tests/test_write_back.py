"""웹 판별 되돌림(feed.write_back, 오늘 탭 수집 인박스 명세 2026-11-13 4절). 전부 합성 자료·임시 폴더·가짜 서버."""
from __future__ import annotations

import datetime as _dt
import json
import os
import stat
import unittest

from agent import config as _config, osutil, runner, store as _store
from agent.adapters import collected as C
from agent.tests.helpers import FakeImportServer, TempHome, connected_config, keystore_with_secrets, write_jsonl
from agent.tests.test_collected import feed_row

AT = "2026-11-13T10:00:00+09:00"


def read_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip() and x.startswith("{") and x.rstrip().endswith("}")]


class WriteBackFeedFileTest(unittest.TestCase):
    """파일 쓰기만 — pending 행의 status·decided_at 만 바꾸고 다른 줄은 원래 바이트 그대로."""

    def setUp(self):
        self.th = TempHome()
        self.path = os.path.join(self.th.root, "feed-queue.jsonl")

    def tearDown(self):
        self.th.cleanup()

    def write(self, lines):
        with open(self.path, "wb") as f:
            f.write(b"".join(lines))

    def test_only_pending_target_lines_change(self):
        other = json.dumps(feed_row(2), ensure_ascii=True).encode() + b"\n"       # 다른 꼴(ASCII 이스케이프) 그대로 남아야
        lines = [json.dumps(feed_row(1), ensure_ascii=False).encode() + b"\r\n", other, b"{not json\n",
                 json.dumps(feed_row(3, status="dropped")).encode() + b"\n",
                 json.dumps(feed_row(4), ensure_ascii=False).encode()]            # 마지막 줄 줄바꿈 없음
        self.write(lines)
        os.chmod(self.path, 0o644)
        r = C.write_back_feed(self.path, {"FEED0001": ("kept", AT), "FEED0003": ("kept", AT),
                                          "FEED0004": ("dropped", AT), "FEED9999": ("kept", AT)})
        self.assertEqual(r, {"applied": 2, "skipped_not_pending": 1, "missing": 1, "retried": 0})
        with open(self.path, "rb") as f:
            got = f.read().splitlines(keepends=True)
        self.assertEqual(got[1:4], lines[1:4])
        self.assertTrue(got[0].endswith(b"\r\n") and not got[4].endswith(b"\n"))
        r1, r4 = json.loads(got[0]), json.loads(got[4])
        self.assertEqual((r1["status"], r1["decided_at"], r4["status"], r4["decided_at"]), ("kept", AT, "dropped", AT))
        want = dict(feed_row(1), status="kept", decided_at=AT)
        self.assertEqual(r1, want)                                                    # 다른 필드 그대로
        self.assertEqual(list(r1)[:len(feed_row(1))], list(feed_row(1)))              # 키 순서 그대로
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)         # 권한 유지

    def test_line_style_kept_and_lone_surrogate(self):
        ascii_line = json.dumps(feed_row(1)).encode() + b"\n"                         # \\u 이스케이프 꼴
        cut = b'{"id": "FEED0002", "status": "pending", "text": "\\ud83d \xec\x9e\x98\xeb\xa6\xb0 \xea\xb8\x80"}\n'
        self.write([ascii_line, cut])
        r = C.write_back_feed(self.path, {"FEED0001": ("kept", AT), "FEED0002": ("dropped", AT)})
        self.assertEqual(r["applied"], 2)
        with open(self.path, "rb") as f:
            got = f.read().splitlines(keepends=True)
        self.assertTrue(got[0].isascii())
        self.assertEqual(json.loads(got[0]), dict(feed_row(1), status="kept", decided_at=AT))
        self.assertEqual(json.loads(got[1])["status"], "dropped")
        self.assertEqual(json.loads(got[1])["text"], json.loads(cut)["text"])        # 짝 없는 서로게이트 그대로

    def test_duplicate_id_changes_last_row_only(self):
        a = json.dumps(feed_row(1, summary="옛 요약"), ensure_ascii=False).encode() + b"\n"
        b = json.dumps(feed_row(1), ensure_ascii=False).encode() + b"\n"
        self.write([a, b])
        C.write_back_feed(self.path, {"FEED0001": ("kept", AT)})
        with open(self.path, "rb") as f:
            got = f.read().splitlines(keepends=True)
        self.assertEqual(got[0], a)
        self.assertEqual(json.loads(got[1])["status"], "kept")

    def test_nothing_applies_no_write(self):
        self.write([json.dumps(feed_row(1, status="kept")).encode() + b"\n"])
        before = os.stat(self.path)
        r = C.write_back_feed(self.path, {"FEED0001": ("dropped", AT)})
        self.assertEqual((r["applied"], r["skipped_not_pending"]), (0, 1))
        after = os.stat(self.path)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    def test_concurrent_change_retried_once(self):
        self.write([json.dumps(feed_row(1)).encode() + b"\n"])
        extra = json.dumps(feed_row(2)).encode() + b"\n"

        def other_writer(attempt):          # 대시보드가 첫 시도 중에 한 줄 더한 상황(원자 교체)
            if attempt == 0:
                with open(self.path, "rb") as f:
                    data = f.read()
                tmp = self.path + ".other"
                with open(tmp, "wb") as f:
                    f.write(data + extra)
                os.replace(tmp, self.path)
        r = C.write_back_feed(self.path, {"FEED0001": ("kept", AT)}, before_replace=other_writer)
        self.assertEqual((r["applied"], r["retried"]), (1, 1))
        rows = read_rows(self.path)
        self.assertEqual([(x["id"], x["status"]) for x in rows], [("FEED0001", "kept"), ("FEED0002", "pending")])

    def test_changed_again_writes_nothing(self):
        self.write([json.dumps(feed_row(1)).encode() + b"\n"])

        def touch(attempt):
            with open(self.path, "ab") as f:
                f.write(json.dumps(feed_row(10 + attempt)).encode() + b"\n")
        with self.assertRaises(C.FileChanged):
            C.write_back_feed(self.path, {"FEED0001": ("kept", AT)}, before_replace=touch)
        self.assertEqual([x["status"] for x in read_rows(self.path)], ["pending"] * 3)

    def test_bad_change_rejected(self):
        self.write([b""])
        with self.assertRaises(ValueError):
            C.write_back_feed(self.path, {"FEED0001": ("removed", AT)})


class WriteBackRunTest(unittest.TestCase):
    """run-once: 업로드 → 판별 목록(커서) → feed 파일. 가짜 서버(명세 2절 꼴)."""

    def setUp(self):
        self.srv, self.th = FakeImportServer(), TempHome()
        self.feed = os.path.join(self.th.root, "feed-queue.jsonl")
        write_jsonl(self.feed, [feed_row(i) for i in range(1, 4)])
        cfg = connected_config(self.th, self.srv.url)
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed, "write_back": True})
        _config.save(self.th.paths, cfg)
        self.ks = keystore_with_secrets()

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def run_once(self):
        return runner.run_once(self.th.paths, ks=self.ks)

    def item_of(self, n):
        """FEED000n 을 올린 원본의 서버 항목 ID."""
        st = _store.Store(self.th.paths)
        try:
            oid = st.event_get("feed", f"feed:FEED{n:04d}")["original_id"]
        finally:
            st.close()
        return self.srv.items[oid]

    def cursor(self):
        st = _store.Store(self.th.paths)
        try:
            return st.cursor_get("decisions:" + _config.load(self.th.paths)["source_instance_id"])
        finally:
            st.close()

    def statuses(self):
        return {r["id"]: r["status"] for r in read_rows(self.feed)}

    def test_web_decisions_written_back_then_resent(self):
        res = self.run_once()
        self.assertEqual(res["upload"]["accepted"], 3)
        self.assertEqual(res["write_back"], {"applied": 0, "skipped_not_pending": 0, "missing": 0, "retried": 0,
                                             "stopped": None})
        self.srv.decisions = [
            {"item_id": self.item_of(1), "state": "kept", "decided_at": AT},
            {"item_id": self.item_of(2), "state": "dropped", "decided_at": AT},
            {"item_id": "i_NotFromThisPc", "state": "kept", "decided_at": AT},
        ]
        res = self.run_once()
        self.assertEqual(res["write_back"], {"applied": 2, "skipped_not_pending": 0, "missing": 1, "retried": 0,
                                             "stopped": None})
        self.assertEqual(self.statuses(), {"FEED0001": "kept", "FEED0002": "dropped", "FEED0003": "pending"})
        self.assertEqual(read_rows(self.feed)[0]["decided_at"], AT)
        self.assertEqual(self.cursor(), "3")
        blob = json.dumps(res, ensure_ascii=False)
        for leak in ("FEED000", "i_", self.th.root):
            self.assertNotIn(leak, blob)                    # 결과엔 수만 — ID·경로 없음
        # 다음 실행: 커서 뒤부터 받는다. 바뀐 행은 새 개정으로 다시 올라간다(kept 는 save 활동도)
        res = self.run_once()
        self.assertEqual(self.srv.decision_calls[-1], "3")
        self.assertEqual(res["write_back"]["applied"], 0)
        self.assertEqual(res["collect"]["staged"], 3)       # 수집 글 2(kept·removed) + save 1
        sent = [json.loads(b) for b in self.srv.bodies()[-3:]]
        self.assertEqual(sorted(o.get("state", o.get("action")) for o in sent), ["active", "kept", "removed"])

    def test_dashboard_decided_first_is_skipped(self):
        self.run_once()
        write_jsonl(self.feed, [feed_row(1, status="dropped"), feed_row(2), feed_row(3)])   # 대시보드에서 먼저 버림
        self.srv.decisions = [{"item_id": self.item_of(1), "state": "kept", "decided_at": AT}]
        res = self.run_once()
        self.assertEqual((res["write_back"]["applied"], res["write_back"]["skipped_not_pending"]), (0, 1))
        self.assertEqual(self.statuses()["FEED0001"], "dropped")

    def test_undo_in_same_page_not_applied(self):
        self.run_once()
        iid = self.item_of(1)
        self.srv.decisions = [{"item_id": iid, "state": "kept", "decided_at": AT},
                              {"item_id": iid, "state": "pending", "decided_at": AT}]
        res = self.run_once()
        self.assertEqual(res["write_back"]["applied"], 0)
        self.assertEqual(self.statuses()["FEED0001"], "pending")

    def test_pages_follow_cursor(self):
        self.run_once()
        self.srv.decisions_page = 1
        self.srv.decisions = [{"item_id": self.item_of(n), "state": "kept", "decided_at": AT} for n in (1, 2, 3)]
        res = self.run_once()
        self.assertEqual(res["write_back"]["applied"], 3)
        self.assertEqual(self.srv.decision_calls[-3:], [None, "1", "2"])   # has_more 가 false 인 쪽에서 멈춘다
        self.assertEqual(set(self.srv.decision_limits), {"200"})             # limit 를 늘 밝힌다
        self.assertEqual(self.cursor(), "3")

    def test_server_errors_keep_cursor(self):
        self.run_once()
        self.srv.decisions = [{"item_id": self.item_of(1), "state": "kept", "decided_at": AT}]
        self.srv.decisions_script = [(404, {"code": "NOT-FOUND"})]
        res = self.run_once()
        self.assertEqual(res["write_back"]["stopped"], "server-404")
        self.assertNotIn("stopped", {k: v for k, v in res["upload"].items() if v})      # 업로드는 멈추지 않음
        self.assertIsNone(self.cursor())                      # 첫 실행의 빈 목록은 커서를 만들지 않는다
        self.srv.decisions_script = [(200, {"next_cursor": "9"})]                     # decisions 없음 = 형식 오류
        res = self.run_once()
        self.assertEqual(res["write_back"]["stopped"], "malformed-200")
        self.assertIsNone(self.cursor())
        st = _store.Store(self.th.paths)
        try:
            self.assertEqual(st.counts()["halts"], [])       # 판별 목록 실패는 멈춤을 만들지 않는다
        finally:
            st.close()
        res = self.run_once()
        self.assertEqual(res["write_back"]["applied"], 1)

    def test_cursor_shapes(self):
        self.run_once()
        iid = self.item_of(1)
        self.srv.decisions_script = [(200, {"decisions": [{"item_id": iid, "state": "kept", "decided_at": AT}],
                                            "next_cursor": None})]
        res = self.run_once()
        self.assertEqual((res["write_back"]["applied"], res["write_back"]["stopped"]), (1, "no-cursor"))
        self.assertIsNone(self.cursor())
        self.srv.decisions_script = [(200, {"decisions": [], "next_cursor": 7}), (200, {"decisions": [], "next_cursor": 7})]
        res = self.run_once()
        self.assertEqual((res["write_back"]["stopped"], self.cursor()), (None, "7"))     # 숫자 커서도 받는다

    def test_unexpected_error_contained(self):
        self.run_once()
        self.srv.decisions = [{"item_id": self.item_of(1), "state": "kept", "decided_at": AT}]
        orig = C.write_back_feed

        def boom(*a, **k):
            raise RuntimeError("synthetic")
        C.write_back_feed = boom
        try:
            res = self.run_once()
        finally:
            C.write_back_feed = orig
        self.assertEqual(res["write_back"]["stopped"], "error")
        self.assertIn("upload", res)
        self.assertIsNone(self.cursor())

    def test_rate_limit_and_bad_cursor(self):
        self.run_once()
        self.srv.decisions = [{"item_id": self.item_of(n), "state": "kept", "decided_at": AT} for n in (1, 2)]
        self.srv.decisions_script = [(429, {"code": "RATE-LIMIT"})]
        res = self.run_once()
        self.assertEqual((res["write_back"]["stopped"], res["write_back"]["applied"]), ("rate-limit", 0))
        self.assertIsNone(self.cursor())
        st = _store.Store(self.th.paths)
        try:
            st.cursor_set("decisions:" + _config.load(self.th.paths)["source_instance_id"], "stale-cursor")
        finally:
            st.close()
        self.srv.decisions_script = [(400, {"code": "ARG-INVALID"})]     # 서버가 모르는 커서 → 처음부터 한 번
        res = self.run_once()
        self.assertEqual((res["write_back"]["applied"], res["write_back"]["stopped"]), (2, None))
        self.assertEqual(self.srv.decision_calls[-2:], ["stale-cursor", None])
        self.assertEqual(self.cursor(), "2")
        self.srv.decisions_script = [(400, {"code": "ARG-INVALID"}), (400, {"code": "ARG-INVALID"})]
        res = self.run_once()
        self.assertEqual(res["write_back"]["stopped"], "server-400")         # 한 번만 처음부터
        self.assertEqual(self.cursor(), "2")

    def test_feed_off_keeps_cursor(self):
        self.run_once()
        self.srv.decisions = [{"item_id": self.item_of(1), "state": "kept", "decided_at": AT}]
        cfg = _config.load(self.th.paths)
        cfg["adapters"]["feed"]["enabled"] = False
        _config.save(self.th.paths, cfg)
        res = self.run_once()
        self.assertEqual(res["write_back"]["stopped"], "feed-off")
        self.assertIsNone(self.cursor())

    def test_off_by_default_no_request(self):
        cfg = _config.load(self.th.paths)
        cfg["adapters"]["feed"]["write_back"] = False
        _config.save(self.th.paths, cfg)
        res = self.run_once()
        self.assertNotIn("write_back", res)
        self.assertEqual(self.srv.decision_calls, [])

    def test_no_upload_no_request(self):
        res = runner.run_once(self.th.paths, ks=self.ks, upload=False)
        self.assertNotIn("write_back", res)
        self.assertEqual(self.srv.decision_calls, [])


class WriteBackConfigTest(unittest.TestCase):
    def test_default_false_and_bool_only(self):
        cfg = _config.default_config()
        self.assertIs(cfg["adapters"]["feed"]["write_back"], False)
        cfg["adapters"]["feed"]["write_back"] = "yes"
        with self.assertRaises(_config.ConfigError):
            _config.validate_config(cfg)


if __name__ == "__main__":
    unittest.main()


class StateResyncTest(unittest.TestCase):
    """state_resync(가안 B): 이 판의 첫 실행 때 한 번, 서버에 항목이 있는 수집 글마다 같은 필드의 새 개정을 지금 판으로 보낸다."""

    def setUp(self):
        self.srv, self.th = FakeImportServer(), TempHome()
        self.feed = os.path.join(self.th.root, "feed-queue.jsonl")
        self.reac = os.path.join(self.th.root, "reactions.jsonl")
        write_jsonl(self.feed, [feed_row(i) for i in range(1, 4)])
        write_jsonl(self.reac, [{"id": "R1", "author": "합성", "text": "반응 첫 줄\n둘째", "kind": "like",
                                 "post_url": "https://example.invalid/r/1", "collected_at": "2026-11-12"}])
        cfg = connected_config(self.th, self.srv.url)
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed})
        cfg["adapters"]["reactions"].update({"enabled": True, "inputs": [
            {"path": self.reac, "format": "reactions", "channel": "linkedin"}]})
        _config.save(self.th.paths, cfg)
        self.ks = keystore_with_secrets()
        res = self.run_once()                                   # 옛 판: 다 올라갔고, 그 실행에선 대상이 없어 끝 표시
        self.assertEqual(res["state_resync"], {"queued": 0, "sent": 0, "done": True})
        self.old = self.collected_bodies()
        self.assertEqual(len(self.old), 4)
        # 새 판의 첫 실행처럼 — 끝 표시를 지우고, 그 사이 허용 규칙 판이 바뀌었다
        st = _store.Store(self.th.paths)
        try:
            st.conn.execute("DELETE FROM cursors WHERE name=?", (runner.RESYNC_FLAG,))
            st.conn.execute("DELETE FROM state_resync")
        finally:
            st.close()
        cfg = _config.load(self.th.paths)
        cfg["policy_revision"] = 2
        _config.save(self.th.paths, cfg)
        self.n0 = len(self.srv.requests)

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def run_once(self):
        return runner.run_once(self.th.paths, ks=self.ks)

    def collected_bodies(self, start=0):
        out = {}
        for _, b in self.srv.requests[start:]:
            o = json.loads(b)
            if o["kind"] == "collected_post":
                out[o["original_id"]] = o
        return out

    def statuses(self):
        st = _store.Store(self.th.paths)
        try:
            return sorted(r[0] for r in st.conn.execute("SELECT status FROM state_resync"))
        finally:
            st.close()

    def test_same_fields_new_revision_current_policy(self):
        res = self.run_once()
        self.assertEqual(res["state_resync"], {"queued": 4, "sent": 4, "done": True})
        new = self.collected_bodies(self.n0)
        self.assertEqual(set(new), set(self.old))               # feed 3 + reactions 1
        meta = ("revision", "previous_revision", "policy_revision")
        for oid, o in new.items():
            old = self.old[oid]
            self.assertEqual(o["previous_revision"], old["revision"])
            self.assertNotEqual(o["revision"], old["revision"])
            self.assertEqual(o["policy_revision"], 2)
            self.assertEqual({k: v for k, v in o.items() if k not in meta}, {k: v for k, v in old.items() if k not in meta})
        n = len(self.srv.requests)
        res = self.run_once()                                   # 한 번만
        self.assertEqual(res["state_resync"], {"queued": 0, "sent": 0, "done": True})
        self.assertEqual(self.collected_bodies(n), {})

    def test_budget_per_run_and_day(self):
        orig = (runner.RESYNC_PER_RUN, runner.RESYNC_PER_DAY, osutil.kst_now)
        runner.RESYNC_PER_RUN, runner.RESYNC_PER_DAY = 2, 3
        day = [_dt.datetime(2026, 11, 13, 10, tzinfo=osutil.KST)]
        osutil.kst_now = lambda: day[0]
        try:
            got = [self.run_once()["state_resync"] for _ in range(3)]
            self.assertEqual(got, [{"queued": 2, "sent": 2, "done": False}, {"queued": 1, "sent": 1, "done": False},
                                   {"queued": 0, "sent": 0, "done": False}])   # 하루 몫(3)을 다 썼다
            day[0] = day[0] + _dt.timedelta(days=1)
            self.assertEqual(self.run_once()["state_resync"], {"queued": 1, "sent": 1, "done": True})
        finally:
            runner.RESYNC_PER_RUN, runner.RESYNC_PER_DAY, osutil.kst_now = orig

    def test_gone_rows_unseen_and_rejected_failed(self):
        write_jsonl(self.feed, [feed_row(1), feed_row(2)])     # FEED0003 이 입력에서 사라짐 — 같은 필드를 만들 수 없다
        self.srv.script = [(422, {"code": "ARG-INVALID"})]     # 첫 다시 보내기는 거절
        res = self.run_once()
        self.assertEqual(res["state_resync"], {"queued": 3, "sent": 2, "done": True})
        self.assertEqual(self.statuses(), ["failed", "sent", "sent", "unseen"])

    def test_only_items_on_server(self):
        st = _store.Store(self.th.paths)
        try:
            ev = st.event_get("feed", "feed:FEED0001")
            st.conn.execute("UPDATE revisions SET server_state='deleted' WHERE original_id=?", (ev["original_id"],))
        finally:
            st.close()
        res = self.run_once()
        self.assertEqual(res["state_resync"], {"queued": 3, "sent": 3, "done": True})
        self.assertNotIn(ev["original_id"], self.collected_bodies(self.n0))
