"""수집 인박스 요약(inbox-digest/1, 2026-11-22 명세 4-2) — 모의 CLI 실행기로만. 전부 합성 자료.

- 기본 꺼짐 · cli_path 없음 · 허용 규칙 없음 · 입력 같음 · 하루 6회 · 남은 시간 220초 미만 → 모델을 부르지 않고 이유
- 입력 = 대기 글 수집일 최신 60개, 원문 본문 없음, 글자 값 300자 안, 격리(도구·MCP 끔, 토큰 없음), 시간 제한 150초
- 출력 검증(키·길이·입력에 없는 URL·차단 꼴) 실패면 버리고, 그날 같은 입력은 다시 부르지 않는다
- run-once: 수집 글 뒤에 줄 세워 올린다(서버가 post_url 을 항목으로 바꾼다)
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest

from agent import config as _config, contract, runner, store as _store
from agent.adapters import inbox_digest as dg
from agent.contract import ContractError
from agent.tests.helpers import TOKEN, FakeImportServer, TempHome, connected_config, keystore_with_secrets, write_jsonl

ALL_TRANSFORMS = list(contract.TRANSFORMS)
OLD_TRANSFORMS = [t for t in ALL_TRANSFORMS if t != "inbox-digest/1"]


def row(i, **over):
    r = {"id": f"IDG{i:04d}", "author": f"가짜 작성자 {i}", "text": f"가짜 첫 줄 {i}\n가짜 본문 비밀 {i}",
         "post_url": f"https://example.invalid/idg/{i}", "status": "pending",
         "collected_at": f"2026-11-{1 + i % 20:02d}T09:30:00+0900", "source": "reddit", "axes_hint": ["C"],
         "grade": "signal", "summary": f"가짜 AI 요약 {i}"}
    r.update(over)
    return r


def themes_for(urls, n=3):
    return [{"name": f"주제 {k}", "line": f"가짜 주제 {k} 한 문장", "post_urls": urls[k::n]} for k in range(n)]


def rows(*ids, **over):
    return [row(i, **over) for i in ids]


def out_of(themes, fence=False):
    inner = json.dumps({"themes": themes}, ensure_ascii=False)
    if fence:
        inner = "```json\n" + inner + "\n```"
    return json.dumps({"type": "result", "is_error": False, "result": inner}, ensure_ascii=False).encode()


class MockCLI:
    """stdin 의 입력 URL 로 정상 출력을 만든다. responses 가 있으면 앞에서부터 꺼낸다(함수면 입력 URL 로 부른다)."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, argv, *, stdin_bytes, env, cwd, timeout):
        self.calls.append({"argv": argv, "stdin": stdin_bytes, "env": env, "cwd": cwd, "timeout": timeout})
        urls = [it["post_url"] for it in json.loads(stdin_bytes.decode("utf-8"))]
        r = self.responses.pop(0) if self.responses else (lambda u: (0, out_of(themes_for(u)), b""))
        if isinstance(r, BaseException):
            raise r
        return r(urls) if callable(r) else r


class _Base(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.feed = os.path.join(self.th.root, "feed.jsonl")
        cfg = connected_config(self.th, "http://127.0.0.1:9")
        cfg["allowed_transforms"] = list(ALL_TRANSFORMS)
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed})
        cfg["summary"]["cli_path"] = "/usr/bin/false"
        cfg["inbox_digest"] = {"enabled": True}
        _config.save(self.th.paths, cfg)
        self.st = _store.Store(self.th.paths)

    def tearDown(self):
        self.st.close()
        self.th.cleanup()

    def cfg(self, **over):
        c = dict(_config.load(self.th.paths))
        c.update(over)
        return c

    def go(self, cli, cfg=None, **kw):
        return dg.collect(self.st, cfg or self.cfg(), paths=self.th.paths, exec_runner=cli, **kw)

    def pending(self):
        out = []
        for r in self.st.pending_revisions():
            out.append(json.loads(self.st.read_pending(r)))
        return out


class GateTest(_Base):
    def test_default_off(self):
        self.assertFalse(_config.default_config()["inbox_digest"]["enabled"])
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI()
        c = self.cfg()
        c.pop("inbox_digest")
        self.assertEqual(self.go(cli, c)["skipped"], "disabled")
        self.assertEqual(self.go(cli, self.cfg(inbox_digest={"enabled": False}))["skipped"], "disabled")
        self.assertEqual(cli.calls, [])

    def test_needs_cli_policy_feed(self):
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI()
        summ = dict(self.cfg()["summary"], cli_path=None)
        self.assertEqual(self.go(cli, self.cfg(summary=summ))["skipped"], "no-cli")
        self.assertEqual(self.go(cli, self.cfg(allowed_transforms=OLD_TRANSFORMS))["skipped"], "policy")
        adapters = self.cfg()["adapters"]
        adapters["feed"] = dict(adapters["feed"], input_path=None)
        self.assertEqual(self.go(cli, self.cfg(adapters=adapters))["skipped"], "no-feed")
        write_jsonl(self.feed, [row(1, status="kept"), row(2, status="dropped"), row(3), row(4)])
        self.assertEqual(self.go(cli)["skipped"], "too-few")               # 대기 2건 — 주제 3개를 만들 수 없다
        adapters = self.cfg()["adapters"]
        adapters["feed"] = dict(adapters["feed"], enabled=False)
        write_jsonl(self.feed, rows(1, 2, 3))
        self.assertEqual(self.go(cli, self.cfg(adapters=adapters))["skipped"], "no-feed")   # feed 를 끄면 요약도 안 한다
        self.assertEqual(cli.calls, [])

    def test_time_left(self):
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI()
        clock = lambda: 1000.0   # noqa: E731
        r = self.go(cli, process_started=1000.0 - 381, clock=clock)      # 남은 219초
        self.assertEqual(r["skipped"], "time")
        self.assertEqual(cli.calls, [])
        r = self.go(cli, process_started=1000.0 - 380, clock=clock)      # 남은 220초 — 돈다
        self.assertTrue(r["staged"])
        self.assertEqual(cli.calls[0]["timeout"], 150.0)

    def test_daily_limit_and_unchanged(self):
        cli = MockCLI()
        for i in range(6):
            write_jsonl(self.feed, [row(j) for j in range(i + 3)])
            self.st.conn.execute("UPDATE revisions SET status='accepted' WHERE status='pending'")   # 앞 판 접수(전송 대기 아님)
            r = self.go(cli)
            self.assertTrue(r["staged"], r)
        self.assertEqual(self.go(cli)["skipped"], "unchanged")              # 입력 그대로 → 부르지 않는다
        self.st.conn.execute("UPDATE revisions SET status='accepted' WHERE status='pending'")
        write_jsonl(self.feed, [row(j) for j in range(9)])
        self.assertEqual(self.go(cli)["skipped"], "daily-limit")
        self.assertEqual(len(cli.calls), 6)

    def test_waiting_previous_not_called(self):
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI()
        self.assertTrue(self.go(cli)["staged"])
        write_jsonl(self.feed, rows(1, 2, 3, 4))
        self.assertEqual(self.go(cli)["skipped"], "waiting")              # 앞 요약이 아직 전송 대기
        self.assertEqual(len(cli.calls), 1)


class InputAndIsolationTest(_Base):
    def test_inputs(self):
        rows = [row(i) for i in range(70)]
        rows += [row(100, status="kept"), row(101, status="dropped"), row(102, post_url="http://insecure.invalid/x"),
                 row(103, collected_at="2026-11-30T10:00:00"),            # 오프셋 없는 시각 — 쓰지 않는다
                 row(5, status="dropped"),                                # 같은 id 의 마지막 행이 이긴다 → 5 는 빠진다
                 row(200, summary="가" * 900, text="나" * 250, collected_at="2026-11-25T00:00:00+0900")]
        write_jsonl(self.feed, rows)
        cli = MockCLI()
        r = self.go(cli)
        self.assertEqual(r["input_n"], 60)
        items = json.loads(cli.calls[0]["stdin"].decode("utf-8"))
        self.assertEqual(len(items), 60)
        urls = [it["post_url"] for it in items]
        self.assertEqual(urls[0], "https://example.invalid/idg/200")       # 수집일 최신 먼저
        self.assertNotIn("https://example.invalid/idg/5", urls)
        for bad in (100, 101, 102, 103):
            self.assertNotIn(f"https://example.invalid/idg/{bad}", urls)
        self.assertNotIn("비밀", cli.calls[0]["stdin"].decode("utf-8"))   # 원문 본문(둘째 줄 뒤)은 보내지 않는다
        for it in items:
            self.assertEqual(set(it), {"post_url", "title", "author", "channel", "axes", "grade", "summary"})
            self.assertLessEqual(len(it["title"]) + len(it["author"] or "") + len(it["summary"] or ""), 300)
        self.assertEqual(items[1]["channel"], "reddit")
        self.assertEqual(items[1]["axes"], ["C"])

    def test_only_rows_feed_would_send(self):
        adapters = self.cfg()["adapters"]
        adapters["feed"] = dict(adapters["feed"], channels={"reddit": "reddit", "hidden": None})
        write_jsonl(self.feed, rows(1, 2, 3) + [
            row(10, source="hidden"),                                      # 채널 매핑 null = 보내지 않는 source
            row(11, source="unknown-src"),                                 # 매핑 없음
            row(12, post_url="https://example.invalid/@who@mail.example.com/p"),   # 계약 이메일 꼴
            row(13, post_url="https://example.invalid/" + "a" * 300)])     # 300자 넘음
        cli = MockCLI()
        r = self.go(cli, self.cfg(adapters=adapters))
        urls = {it["post_url"] for it in json.loads(cli.calls[0]["stdin"].decode("utf-8"))}
        self.assertEqual(urls, {f"https://example.invalid/idg/{i}" for i in (1, 2, 3)})
        self.assertTrue(r["staged"], r)

    def test_full_inbox_with_long_urls_stages(self):
        # 실제 글 주소 길이(150자 안팎) 60개 — URL 은 digest 키에만 실려 body 상한(8000자)과 무관하고 요청 상한(64KB) 안
        write_jsonl(self.feed, [row(i, post_url=f"https://example.invalid/feed/update/{i:04d}-" + "x" * 110)
                                for i in range(60)])
        r = self.go(MockCLI())
        self.assertTrue(r["staged"], r)
        obj = self.pending()[0]
        self.assertEqual(sum(len(t["post_urls"]) for t in obj["digest"]["themes"]), 60)
        self.assertNotIn("https://", obj["body"])

    def test_handle_in_post_url_not_quarantined(self):
        # likes·reactions 로 아는 계정의 핸들이 수집 글 주소에 들어 있어도 요약은 격리하지 않는다(대조는 제목·body 만)
        self.st.person_hmac("hn_SynthSpace01", "synthnet", "synth_handle", lambda: "h" * 64)
        write_jsonl(self.feed, [row(i, post_url=f"https://example.invalid/@synth_handle/post/{i}") for i in range(3)])
        r = self.go(MockCLI())
        self.assertTrue(r["staged"], r)
        self.st.conn.execute("UPDATE revisions SET status='accepted' WHERE status='pending'")
        write_jsonl(self.feed, rows(4, 5, 6))
        named = lambda u: (0, out_of([dict(t, line="synth_handle 의 글") for t in themes_for(u)]), b"")   # noqa: E731
        r = self.go(MockCLI([named]))
        self.assertEqual(r["failed"], "not-staged")                    # 주제 문장에 들어가면 격리

    def test_isolation(self):
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI()
        self.go(cli)
        call = cli.calls[0]
        argv = call["argv"]
        self.assertEqual(argv[:3], ["/usr/bin/false", "-p", dg.PROMPT])
        for flag in ("--tools", "--strict-mcp-config", "--max-turns"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        blob = json.dumps(call["env"]) + " ".join(argv) + call["stdin"].decode("utf-8")
        self.assertNotIn(TOKEN, blob)
        self.assertEqual(call["cwd"], self.th.paths.summary_work)


class OutputTest(_Base):
    def staged_body(self):
        p = self.pending()
        self.assertEqual(len(p), 1)
        return p[0], p[0]["digest"]

    def test_success_shape(self):
        write_jsonl(self.feed, [row(i) for i in range(5)])
        r = self.go(MockCLI([lambda u: (0, out_of(themes_for(u), fence=True), b"")]))
        self.assertEqual((r["staged"], r["themes"], r["input_n"], r["failed"]), (True, 3, 5, None))
        obj, body = self.staged_body()
        self.assertEqual((obj["kind"], obj["transform_version"], obj["title"]), ("self_text", "inbox-digest/1", "인박스 요약"))
        self.assertEqual(set(body), {"themes", "input_n", "made_at"})
        self.assertEqual(body["input_n"], 5)
        self.assertEqual(obj["source_created_at"], body["made_at"])
        self.assertTrue(body["made_at"].endswith("+09:00"))
        self.assertEqual({u for t in body["themes"] for u in t["post_urls"]},
                         {f"https://example.invalid/idg/{i}" for i in range(5)})
        # body = 사람이 읽는 줄(「이름: 문장」, URL 없음)
        self.assertEqual(obj["body"], "\n".join(f"{t['name']}: {t['line']}" for t in body["themes"]))
        contract.validate(obj)

    def test_new_digest_is_new_revision_of_same_original(self):
        write_jsonl(self.feed, rows(1, 2, 3))
        self.go(MockCLI())
        first = self.pending()[0]
        self.st.conn.execute("UPDATE revisions SET status='accepted' WHERE status='pending'")
        write_jsonl(self.feed, rows(1, 2, 3, 4))
        self.go(MockCLI())
        second = [o for o in self.pending() if o["revision"] != first["revision"]][0]
        self.assertEqual(second["original_id"], first["original_id"])
        self.assertEqual(second["previous_revision"], first["revision"])

    def test_rejects(self):
        write_jsonl(self.feed, [row(i) for i in range(4)])
        bad = {
            "theme-count": lambda u: themes_for(u, 2),
            "theme-count ": lambda u: themes_for(u, 8),
            "name-length": lambda u: [dict(t, name="가" * 21) for t in themes_for(u)],
            "line-length": lambda u: [dict(t, line="가" * 81) for t in themes_for(u)],
            "unknown-url": lambda u: [dict(t, post_urls=["https://example.invalid/not-input"]) for t in themes_for(u)],
            "blocked-text": lambda u: [dict(t, line="자세히는 https://example.invalid/x 참고") for t in themes_for(u)],
            "theme-shape": lambda u: [dict(t, extra=1) for t in themes_for(u)],
        }
        for reason, make in bad.items():
            self.st.cursor_set(dg.FAILED_CURSOR, "")                         # 같은 입력을 여러 출력으로 시험한다
            self.st.conn.execute("DELETE FROM cursors WHERE name LIKE 'inbox_digest_day:%'")
            r = self.go(MockCLI([lambda u, m=make: (0, out_of(m(u)), b"")]))
            self.assertEqual((r["staged"], r["failed"]), (False, reason.strip()), reason)
        self.assertEqual(self.pending(), [])

    def test_url_kept_in_first_theme_only(self):
        write_jsonl(self.feed, rows(0, 1, 2, 3))
        u = [f"https://example.invalid/idg/{i}" for i in range(4)]
        dup = [{"name": "가", "line": "하나", "post_urls": [u[0], u[1]]}, {"name": "나", "line": "둘", "post_urls": [u[1], u[2]]},
               {"name": "다", "line": "셋", "post_urls": [u[3], u[0]]}]
        r = self.go(MockCLI([(0, out_of(dup), b"")]))
        self.assertTrue(r["staged"], r)
        self.assertEqual([t["post_urls"] for t in self.pending()[0]["digest"]["themes"]],
                         [[u[0], u[1]], [u[2]], [u[3]]])
        self.st.conn.execute("UPDATE revisions SET status='accepted' WHERE status='pending'")
        write_jsonl(self.feed, rows(0, 1, 2, 3, 4))
        allsame = [{"name": "가", "line": "하나", "post_urls": [u[0]]}, {"name": "나", "line": "둘", "post_urls": [u[0]]},
                   {"name": "다", "line": "셋", "post_urls": [u[1]]}]
        self.assertEqual(self.go(MockCLI([(0, out_of(allsame), b"")]))["failed"], "empty-theme")

    def test_failed_input_not_retried_same_day(self):
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI([(1, b"", b"boom"), (0, b"not json", b""), subprocess.TimeoutExpired("x", 150)])
        self.assertEqual(self.go(cli)["failed"], "exit-1")
        self.assertEqual(self.go(cli)["skipped"], "failed-today")
        self.assertEqual(len(cli.calls), 1)
        write_jsonl(self.feed, rows(1, 2, 3, 4))                       # 입력이 바뀌면 다시 부른다
        self.assertEqual(self.go(cli)["failed"], "output-not-json")
        write_jsonl(self.feed, rows(5, 6, 7))
        self.assertEqual(self.go(cli)["failed"], "timeout")
        write_jsonl(self.feed, rows(8, 9, 10))
        self.assertEqual(self.go(MockCLI([(1, b"", b"Not logged in")]))["failed"], "login")
        self.assertEqual(self.pending(), [])


class ContractTest(unittest.TestCase):
    def digest(self, **over):
        d = {"themes": [{"name": f"주제{k}", "line": "가짜 한 문장", "post_urls": [f"https://example.invalid/{k}"]}
                        for k in range(3)], "input_n": 3, "made_at": "2026-11-22T09:00:00+09:00"}
        d.update(over)
        return d

    def obj(self, digest=None, **over):
        o = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": "is_" + "5a" * 12,
             "original_id": "o_" + "1" * 32, "revision": "v_" + "2" * 32, "previous_revision": None,
             "execution": "attended", "policy_revision": 1, "kind": "self_text", "transform_version": "inbox-digest/1",
             "title": "인박스 요약", "body": "주제0: 가짜 한 문장\n주제1: 가짜 한 문장\n주제2: 가짜 한 문장",
             "digest": digest if digest is not None else self.digest()}
        o.update(over)
        return {k: v for k, v in o.items() if v is not ...}

    def code(self, obj, code, field):
        with self.assertRaises(ContractError) as cm:
            contract.validate(obj)
        self.assertEqual((cm.exception.code, cm.exception.field), (code, field))

    def test_valid_and_digest_only_here(self):
        contract.validate(self.obj())
        self.code(self.obj(digest=...), "MISSING", "digest")
        self.code(self.obj(transform_version="self-text/1"), "UNKNOWN-FIELD", "digest")
        # body 는 다른 self_text 와 같다 — URL 차단, 8000자 상한
        self.code(self.obj(body="본문 https://example.invalid/x"), "BLOCKED-URL", "body")
        self.code(self.obj(body="가" * 8001), "TOO-LONG", "body")

    def test_shape(self):
        t = self.digest()["themes"]
        d = self.digest
        self.code(self.obj("not object"), "DIGEST", "digest")
        self.code(self.obj(d(extra=1)), "DIGEST", "digest")
        self.code(self.obj(d(input_n=61)), "DIGEST", "digest.input_n")
        self.code(self.obj(d(made_at="2026-11-22T09:00:00")), "DIGEST", "digest.made_at")
        self.code(self.obj(d(themes=t[:2])), "DIGEST", "digest.themes")
        self.code(self.obj(d(themes=[dict(t[0], name="가" * 21)] + t[1:])), "DIGEST", "digest.themes[0].name")
        self.code(self.obj(d(themes=[dict(t[0], line="줄\n바꿈")] + t[1:])), "DIGEST", "digest.themes[0].line")
        self.code(self.obj(d(themes=[dict(t[0], line="www.example.com 참고")] + t[1:])), "BLOCKED-URL",
                  "digest.themes[0].line")
        self.code(self.obj(d(themes=[dict(t[0], post_urls=["http://example.invalid/x"])] + t[1:])), "DIGEST",
                  "digest.themes[0].post_urls")
        self.code(self.obj(d(themes=[dict(t[0], post_urls=[])] + t[1:])), "DIGEST", "digest.themes[0].post_urls")
        self.code(self.obj(d(themes=[t[0], dict(t[1], post_urls=t[0]["post_urls"]), t[2]])), "DIGEST",
                  "digest.themes[1].post_urls")                                  # 한 글은 한 주제에만
        self.code(self.obj(d(themes=[dict(t[0], post_urls=["https://example.invalid/" + "a" * 300])] + t[1:])),
                  "DIGEST", "digest.themes[0].post_urls")
        self.code(self.obj(generation={"method": "none"}), "UNKNOWN-FIELD", "generation")
        self.code(self.obj(axis_code="A"), "UNKNOWN-FIELD", "axis_code")
        # post_urls 도 이메일·경로 꼴은 막는다(URL 꼴만 허용)
        self.code(self.obj(d(themes=[dict(t[0], post_urls=["https://example.invalid/u/a@b.example.com"])] + t[1:])),
                  "BLOCKED-EMAIL", "digest.themes[0].post_urls[0]")


class ConfigTest(unittest.TestCase):
    def test_validate(self):
        cfg = _config.default_config()
        _config.validate_config(cfg)
        for bad in ({"enabled": "yes"}, {"enabled": True, "extra": 1}, []):
            c = _config.default_config()
            c["inbox_digest"] = bad
            with self.assertRaises(_config.ConfigError):
                _config.validate_config(c)

    def test_policy_refresh_when_enabled(self):
        cfg = _config.default_config()
        cfg["allowed_transforms"] = list(OLD_TRANSFORMS)
        self.assertFalse(runner._policy_missing_transforms(cfg))
        cfg["inbox_digest"] = {"enabled": True}
        self.assertTrue(runner._policy_missing_transforms(cfg))


class RunOnceTest(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.ks = keystore_with_secrets()
        self.srv = FakeImportServer()
        self.feed = os.path.join(self.th.root, "feed.jsonl")
        cfg = connected_config(self.th, self.srv.url)
        cfg["allowed_actions"] = list(contract.ACTIONS)
        cfg["allowed_transforms"] = list(ALL_TRANSFORMS)
        cfg["adapters"]["feed"].update({"enabled": True, "input_path": self.feed})
        cfg["summary"]["cli_path"] = "/usr/bin/false"
        cfg["inbox_digest"] = {"enabled": True}
        _config.save(self.th.paths, cfg)
        self.srv.device_info["policy"] = {"actions": list(contract.ACTIONS), "transform_versions": list(ALL_TRANSFORMS),
                                          "axes": []}

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def test_digest_uploads_after_posts(self):
        write_jsonl(self.feed, rows(0, 1, 2))
        cli = MockCLI()
        res = runner.run_once(self.th.paths, ks=self.ks, exec_runner=cli)
        self.assertTrue(res["inbox_digest"]["staged"], res["inbox_digest"])
        sent = [json.loads(b) for b in self.srv.bodies()]
        tvs = [o["transform_version"] for o in sent]
        self.assertEqual(tvs[-1], "inbox-digest/1")                      # 수집 글이 먼저 올라간다
        self.assertEqual(tvs.count("collected-post/1"), 3)
        res = runner.run_once(self.th.paths, ks=self.ks, exec_runner=cli)
        self.assertEqual(res["inbox_digest"]["skipped"], "unchanged")
        self.assertEqual(len(cli.calls), 1)

    def test_off_by_default_no_call(self):
        cfg = _config.load(self.th.paths)
        cfg["inbox_digest"] = {"enabled": False}
        _config.save(self.th.paths, cfg)
        write_jsonl(self.feed, rows(1, 2, 3))
        cli = MockCLI()
        res = runner.run_once(self.th.paths, ks=self.ks, exec_runner=cli)
        self.assertEqual(res["inbox_digest"]["skipped"], "disabled")
        self.assertEqual(cli.calls, [])


if __name__ == "__main__":
    unittest.main()
