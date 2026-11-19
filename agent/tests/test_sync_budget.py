"""업로드 시간 예산(stopped time-budget). 데스크톱 앱이 run-once 를 끊기 전에 업로드가 스스로 멈추고 뒷정리가 돈다.
전부 합성 자료, 임시 폴더, 가짜 서버, 가짜 시계."""
from __future__ import annotations

import os
import unittest

from agent import config as _config, runner, store as _store, uploader as _uploader
from agent.tests.helpers import TOKEN, FakeImportServer, TempHome, connected_config, keystore_with_secrets, write_jsonl
from agent.tests.test_collected import feed_row

# 데스크톱 앱의 run-once 강제 종료 한도(desktop/src/main.cjs command(): run-once 600000ms). JS 상수라 여기서 읽지 않고 숫자로 둔다
DESKTOP_RUN_ONCE_KILL_SEC = 600
# 판별 되돌림 최악(쪽 상한 × 간격) 밖의 뒷정리(state_resync 정리, state 집계, 요청 지연)에 남겨 둘 여유
CLEANUP_MARGIN_SEC = 30


class FakeClock:
    """sleep 할 때마다 step 초씩 간다(실제로 기다리지 않는다)."""

    def __init__(self, step: float):
        self.t, self.step = 0.0, step

    def clock(self) -> float:
        return self.t

    def sleep(self, _sec) -> None:
        self.t += self.step


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.srv, self.th = FakeImportServer(), TempHome()
        self.feed = os.path.join(self.th.root, "feed-queue.jsonl")
        write_jsonl(self.feed, [feed_row(i) for i in range(1, 4)])
        cfg = connected_config(self.th, self.srv.url)
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed, "write_back": True})
        cfg["upload"]["min_interval_sec"] = 1        # 간격 sleep 이 돌아야 가짜 시계가 간다
        _config.save(self.th.paths, cfg)
        self.ks = keystore_with_secrets()

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def counts(self):
        st = _store.Store(self.th.paths)
        try:
            return st.counts()
        finally:
            st.close()

    def factory(self, fake):
        return lambda url, token, timeout: _uploader.Uploader(url, token, timeout=timeout, sleep=fake.sleep,
                                                              clock=fake.clock)

    def test_default_budget_leaves_room_before_desktop_kill(self):
        # 업로드 예산 + write_back 최악(쪽 상한 × 기본 업로드 간격) + 여유 < 데스크톱 종료 한도
        interval = float(_config.default_config()["upload"]["min_interval_sec"])
        write_back_worst = runner.WRITE_BACK_MAX_PAGES * interval
        self.assertLess(_uploader.UPLOAD_BUDGET_SEC + write_back_worst + CLEANUP_MARGIN_SEC, DESKTOP_RUN_ONCE_KILL_SEC)

    def test_upload_stops_at_budget_and_keeps_rest_pending(self):
        runner.run_once(self.th.paths, ks=self.ks, upload=False)               # 3건 전송 대기
        fake = FakeClock(300)                                                   # 간격마다 300초: 2번째 300, 3번째 600
        st = _store.Store(self.th.paths)
        try:
            up = self.factory(fake)(self.srv.url, TOKEN, 30)
            res = up.run(st, max_n=100, min_interval=1)        # 기본 예산(UPLOAD_BUDGET_SEC)
        finally:
            st.close()
        self.assertEqual(res["stopped"], "time-budget")
        self.assertEqual((res["sent"], res["accepted"]), (2, 2))
        c = self.counts()
        self.assertEqual((c["accepted"], c["pending"]), (2, 1))
        self.assertEqual(len(os.listdir(self.th.paths.pending)), 1)              # 남은 건의 대기 파일 그대로

    def test_next_run_continues_after_budget_stop(self):
        res = runner.run_once(self.th.paths, ks=self.ks, uploader_factory=self.factory(FakeClock(300)))
        self.assertEqual(res["upload"]["stopped"], "time-budget")
        res = runner.run_once(self.th.paths, ks=self.ks)                        # 실제 시계: 예산 안
        self.assertEqual(res["upload"]["accepted"], 1)
        self.assertIsNone(res["upload"]["stopped"])
        self.assertEqual(self.counts()["pending"], 0)

    def test_run_once_cleanup_runs_after_budget_stop(self):
        res = runner.run_once(self.th.paths, ks=self.ks, uploader_factory=self.factory(FakeClock(300)))
        self.assertEqual(res["upload"]["stopped"], "time-budget")
        self.assertEqual(res["upload"]["accepted"], 2)
        self.assertIn("write_back", res)                                        # 판별 되돌림이 돌았다
        self.assertIsNone(res["write_back"]["stopped"])
        self.assertIn("state_resync", res)                                      # _resync.finish 가 돌았다
        self.assertIn("state", res)
        self.assertEqual(self.counts()["pending"], 1)

    def test_no_budget_stop_when_within_budget(self):
        res = runner.run_once(self.th.paths, ks=self.ks, uploader_factory=self.factory(FakeClock(1)))
        self.assertEqual(res["upload"]["accepted"], 3)
        self.assertIsNone(res["upload"]["stopped"])


if __name__ == "__main__":
    unittest.main()
