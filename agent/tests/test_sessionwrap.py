"""세션 정리 폴더 → 내 글(승인 대기, session-wrap/1). 가짜 세션 정리 글로만 — 묶음 나누기 · `→ 남긴 곳:` 줄 빼기 ·
날짜 이름 파일만 · 개정·중복 · 정책에 없으면 안 만듦 · 기본 꺼짐 · run_once 업로드 · 경로는 가리고 보냄(URL·이메일은 격리)."""
from __future__ import annotations

import json
import os
import unittest

from agent import config as _config, contract, runner, sessionwrap, store as _store
from agent.tests.helpers import FakeImportServer, TempHome, connected_config, keystore_with_secrets

STORY = """---
title: 세션 스토리 합성
updated: 2030-01-02
---

# 세션 스토리 — 2030-01-02

머리글 문단은 보내지 않는다.

## 가짜 화면을 줄이기로 정했다 (합성)
합성 문단이다. 내가 칸을 줄이자고 했고 그래서 한 칸만 남겼다.
→ 남긴 곳: 합성 스토리
정본 후보: 칸은 하나만 — 새 결정

---

## 옛 양식 묶음 (합성)

### 상황 (문제)
합성 상황 문장.

### 내 판단
- 합성 판단 한 줄.

```
## 울타리 안 제목은 경계가 아니다
```

## 본문 없는 묶음

## 가짜 화면을 줄이기로 정했다 (합성)
같은 제목 두 번째 묶음.
"""


class ParseTest(unittest.TestCase):
    def test_blocks(self):
        got = sessionwrap.parse(STORY)
        self.assertEqual([t for t, _ in got], ["가짜 화면을 줄이기로 정했다 (합성)", "옛 양식 묶음 (합성)", "가짜 화면을 줄이기로 정했다 (합성)"])
        first = got[0][1]
        self.assertNotIn("남긴 곳", first)
        self.assertIn("정본 후보: 칸은 하나만 — 새 결정", first)
        self.assertNotIn("머리글", "".join(b for _, b in got))
        self.assertIn("### 내 판단", got[1][1])
        self.assertIn("## 울타리 안 제목은 경계가 아니다", got[1][1])
        self.assertEqual(got[2][1], "같은 제목 두 번째 묶음.")

    def test_heading_keeps_inner_hash(self):
        self.assertEqual(sessionwrap.parse("## C# 쓰기로 정했다 ##\n문단")[0][0], "C# 쓰기로 정했다")


# 가짜 경로만(합성) — 계약 path 규칙의 접두마다, 여러 앞 경계. 홈 접두는 이어 붙여 만든다(crm.py check 스크럽이 레포 글자를 본다)
U = "/" + "Users/"
PATH_CASES = [
    ("파일 /Volumes/disk/x.md 를 봤다", "파일 ‹경로› 를 봤다", 1),
    ("`~/합성/세션정리/2030-01-02.md`에 남김", "`‹경로›`에 남김", 1),
    ("(~/a/b) 와 \"" + U + "someone/x y\"", "(‹경로›) 와 \"‹경로› y\"", 2),
    ("'/home/u/a' /private/tmp/x /var/log/y", "'‹경로›' ‹경로› ‹경로›", 3),
    ("D:\\data\\x\\y.txt 확인", "‹경로› 확인", 1),
    ("공유 \\\\host\\share\\f 끝", "공유 ‹경로› 끝", 1),
    ("표 |~/p| 칸", "표 |‹경로›| 칸", 1),
    ("경로:" + U + "x 붙음", "경로:‹경로› 붙음", 1),
    ("server/var/x · a~/b · 2/3 은 그대로", "server/var/x · a~/b · 2/3 은 그대로", 0),
]


class RedactTest(unittest.TestCase):
    def test_cases(self):
        for src, want, n in PATH_CASES:
            with self.subTest(src):
                self.assertEqual(sessionwrap.redact_paths(src), (want, n))

    def test_masked_never_blocked_as_path(self):
        """불변식 — 가린 결과는 계약 path 규칙에 걸리지 않는다(원문은 걸리는 것도 있다)."""
        paths = [pat for code, pat in contract._BLOCK_PATTERNS if code == "path"]
        for src, _, _ in PATH_CASES:
            out, _ = sessionwrap.redact_paths(src)
            with self.subTest(src):
                self.assertFalse(any(p.search(out) for p in paths), out)
        self.assertTrue(any(p.search(PATH_CASES[0][0]) for p in paths))

    def test_mask_matches_server_constant(self):
        self.assertEqual(sessionwrap.PATH_MASK, "‹경로›")   # 서버 imports.SESSION_WRAP_PATH_MASK — 서버가 승인 때 개수를 센다


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.wrap = os.path.join(self.th.root, "wrap")
        os.makedirs(os.path.join(self.wrap, "sub"))
        self.cfg = connected_config(self.th, "http://127.0.0.1:9")
        self.cfg["allowed_transforms"] = ["self-text/1", "session-wrap/1"]
        self.cfg["session_wrap"] = {"enabled": True, "folders": [self.wrap]}
        _config.save(self.th.paths, self.cfg)
        self.st = _store.Store(self.th.paths)

    def tearDown(self):
        self.st.close()
        self.th.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.wrap, name), "w", encoding="utf-8") as f:
            f.write(text)

    def go(self):
        return sessionwrap.collect(self.st, _config.load(self.th.paths))

    def pending(self):
        out = []
        for n in sorted(os.listdir(self.th.paths.pending)):
            with open(os.path.join(self.th.paths.pending, n), "rb") as f:
                out.append(json.loads(f.read()))
        return out

    def test_default_off(self):
        self.assertEqual(_config.default_config()["session_wrap"], {"enabled": False, "folders": []})
        cfg = _config.load(self.th.paths)
        cfg["session_wrap"]["enabled"] = False
        self.write("2030-01-02.md", STORY)
        self.assertEqual(sessionwrap.collect(self.st, cfg)["skipped"], "disabled")
        self.assertEqual(self.pending(), [])

    def test_only_dated_files_one_request_per_block(self):
        self.write("2030-01-02.md", STORY)
        self.write("decisions.md", "## 정본은 보내지 않는다\n문단")
        self.write("2030-13-40.md", "## 없는 날짜\n문단")
        with open(os.path.join(self.wrap, "sub", "2030-01-03.md"), "w", encoding="utf-8") as f:
            f.write("## 하위 폴더\n문단")
        r = self.go()
        self.assertEqual((r["files"], r["blocks"], r["staged"]), (1, 3, 3))
        objs = self.pending()
        self.assertEqual({o["transform_version"] for o in objs}, {"session-wrap/1"})
        self.assertEqual({o["kind"] for o in objs}, {"self_text"})
        self.assertEqual({o["source_date"] for o in objs}, {"2030-01-02"})
        self.assertEqual(len({o["original_id"] for o in objs}), 3)   # 같은 제목 두 묶음도 따로
        self.assertNotIn("generation", objs[0])
        for o in objs:
            contract.validate(o)

    def test_rerun_unchanged_and_edit_makes_revision(self):
        self.write("2030-01-02.md", "## 합성 제목\n첫 문단")
        self.assertEqual(self.go()["staged"], 1)
        self.assertEqual(self.go()["staged"], 0)   # 같은 내용 — 새 요청 없음
        (first,) = self.pending()
        self.st.conn.execute("UPDATE revisions SET status='accepted' WHERE original_id=?", (first["original_id"],))
        self.write("2030-01-02.md", "## 합성 제목\n고친 문단")
        self.assertEqual(self.go()["staged"], 1)
        objs = [o for o in self.pending() if o["revision"] != first["revision"]]
        self.assertEqual(objs[0]["original_id"], first["original_id"])
        self.assertEqual(objs[0]["previous_revision"], first["revision"])

    def test_policy_without_transform_makes_nothing(self):
        self.cfg["allowed_transforms"] = ["self-text/1"]
        _config.save(self.th.paths, self.cfg)
        self.write("2030-01-02.md", STORY)
        self.assertEqual(self.go()["skipped"], "policy")
        self.assertEqual(self.pending(), [])

    def test_path_is_masked_and_sent(self):
        self.write("2030-01-02.md", "## 합성 제목 ~/합성/x.md\n파일 /Volumes/disk/x.md 를 봤다\n`~/합성/y.md`에 남김")
        r = self.go()
        self.assertEqual((r["staged"], r["redacted"]), (1, 3))
        (o,) = self.pending()
        self.assertEqual(o["title"], "합성 제목 ‹경로›")
        self.assertEqual(o["body"], "파일 ‹경로› 를 봤다\n`‹경로›`에 남김")
        self.assertNotIn("/Volumes/", json.dumps(o, ensure_ascii=False))
        contract.validate(o)

    def test_url_and_email_still_quarantined(self):
        self.write("2030-01-02.md", "## 합성 URL\n링크 https://example.invalid/x 를 봤다\n\n## 합성 메일\n주소 a@example.invalid 로 보냄")
        r = self.go()
        self.assertEqual((r["blocks"], r["staged"]), (2, 0))
        self.assertEqual(self.pending(), [])

    def test_missing_folder_does_not_stop_others(self):
        self.cfg["session_wrap"]["folders"] = [os.path.join(self.th.root, "none"), self.wrap]
        _config.save(self.th.paths, self.cfg)
        self.write("2030-01-02.md", "## 합성 제목\n문단")
        r = self.go()
        self.assertEqual((r["missing_folders"], r["staged"]), (1, 1))

    def test_symlink_file_skipped(self):
        outside = os.path.join(self.th.root, "outside.md")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("## 밖\n문단")
        os.symlink(outside, os.path.join(self.wrap, "2030-01-05.md"))
        self.assertEqual(self.go()["files"], 0)

    def test_config_rejects_relative_folder(self):
        cfg = _config.load(self.th.paths)
        cfg["session_wrap"]["folders"] = ["relative/dir"]
        with self.assertRaises(_config.ConfigError):
            _config.validate_config(cfg)
        cfg["session_wrap"] = {"enabled": True, "folders": [], "extra": 1}
        with self.assertRaises(_config.ConfigError):
            _config.validate_config(cfg)

    def test_run_once_uploads_session_wrap(self):
        srv = FakeImportServer()
        try:
            self.cfg["server_url"] = srv.url
            self.cfg["allowed_transforms"] = None
            _config.save(self.th.paths, self.cfg)
            self.write("2030-01-02.md", "## 합성 제목\n합성 문단")
            res = runner.run_once(self.th.paths, ks=keystore_with_secrets())
            self.assertEqual(res["session_wrap"]["staged"], 1)
            (body,) = [json.loads(b) for b in srv.bodies()]
            self.assertEqual((body["transform_version"], body["title"], body["execution"]),
                             ("session-wrap/1", "합성 제목", "attended"))
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
