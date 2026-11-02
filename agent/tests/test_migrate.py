"""이관 업로더(agent/migrate.py) — 합성 자료 · 가짜 HTTP 서버 · 메모리 키 저장소. 실제 Keychain·서버를 쓰지 않는다."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import secrets
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import cli, keystore, migrate
from agent.tests.helpers import MemoryKeyStore, TempHome

VEC = os.path.join(os.path.dirname(__file__), "..", "..", "server", "contract", "imports", "vectors",
                   "board-migration-2-normalize.json")
TOKEN = "mig_mt_0123456789abcdef." + "T" * 43
SI = "pc-synth-1"
BODY_MARK = "SYNTH-BODY-MARK"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _server_jcs(v) -> bytes:   # 서버 imports.jcs 와 같은 식
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def rec(i, **over):
    it = {"original_id": migrate.recommended_original_id(SI, "journal/synth.md", f"a{i}"), "unit_kind": "record",
          "author_kind": "self", "text_process": "verbatim", "generation_kind": "human",
          "primary_date": {"kind": "written", "value": "2026-01-10"}, "review": {"state": "reviewed"}, "sensitivity": "normal",
          "body": f"{BODY_MARK} {i} 합성 본문\r\n둘째 줄  "}
    it.update(over)
    return it


def src(i, **over):
    it = {"original_id": migrate.recommended_original_id(SI, "sources", f"s{i}"), "unit_kind": "source",
          "source": {"kind": "file", "name": f"합성 출처 {i}", "location": "ab" * 32}}
    it.update(over)
    return it


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
            f.write("\n")


# ── 가짜 서버(토큰 경로만) ─────────────────────────────────

class FakeServer:
    def __init__(self, token=TOKEN):
        self.token = token
        self.plans = {}
        self.requests = []          # (method, path, auth_ok)
        self.force = {}             # (method, op) → (status, payload, headers) 한 번
        self.chunk_sizes = []
        st = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def _send(self, status, payload, headers=None):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("cache-control", "no-store")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                u = urllib.parse.urlsplit(self.path)
                st.requests.append((method, u.path, self.headers.get("Authorization") == "Bearer " + st.token))
                status, payload, headers = st.route(method, u.path, urllib.parse.parse_qs(u.query), raw,
                                                    self.headers.get("Authorization", ""))
                self._send(status, payload, headers)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    @staticmethod
    def err(status, code, msg="합성 오류", **detail):
        p = {"code": code, "msg": msg}
        if detail:
            p["detail"] = detail
        return status, p, {}

    def _plan_out(self, p, items=True):
        d = {k: p[k] for k in ("plan_id", "state", "item_count", "staged_bytes", "plan_hash", "source_instance", "expires_at")}
        acts, units = {}, {}
        for x in p["rows"]:
            if x.get("action"):
                acts[x["action"]] = acts.get(x["action"], 0) + 1
                units.setdefault(x["unit_kind"], {})
                units[x["unit_kind"]][x["action"]] = units[x["unit_kind"]].get(x["action"], 0) + 1
        d["counts"] = {"actions": acts, "units": units}
        if items:
            d["items"] = [{k: x[k] for k in ("seq", "original_id", "source_revision", "unit_kind", "content_hash", "action", "reason")}
                          for x in p["rows"]]
        return d

    def route(self, method, path, q, raw, auth):
        key = (method, path.rsplit("/", 1)[-1] if path.count("/") > 4 else ("plan" if path.count("/") == 4 else "plans"))
        if key in self.force:
            return self.force.pop(key)
        if auth != "Bearer " + self.token:
            return self.err(401, "AUTH-INVALID")
        parts = path.strip("/").split("/")   # api migration plans [pid] [op]
        if parts[:3] != ["api", "migration", "plans"]:
            return self.err(404, "NOT-FOUND")
        if len(parts) == 3 and method == "POST":
            body = json.loads(raw)
            if any(k in body for k in migrate.OWNER_KEYS):
                return self.err(400, "CONTRACT-INVALID", "owner: owner_field_not_allowed")
            pid = "mp_" + secrets.token_hex(12)
            self.plans[pid] = {"plan_id": pid, "state": "staged", "item_count": 0, "staged_bytes": 0, "plan_hash": None,
                               "source_instance": body["source_instance"], "expires_at": "2026-11-05T00:00:00+09:00", "rows": []}
            return 201, self._plan_out(self.plans[pid]), {}
        pid = parts[3]
        p = self.plans.get(pid)
        if not p:
            return self.err(404, "NOT-FOUND")
        op = parts[4] if len(parts) > 4 else ""
        if op == "" and method == "GET":
            return 200, self._plan_out(p), {}
        if op == "items" and method == "POST":
            if p["state"] != "staged":
                return self.err(409, "PLAN-STATE", state=p["state"])
            if len(raw) > migrate.CHUNK_MAX_BYTES:
                return self.err(413, "PAYLOAD-LIMIT")
            off = int(q["offset"][0])
            if off != p["item_count"]:
                return self.err(409, "CHUNK-OFFSET", received=p["item_count"])
            text = raw.decode("utf-8")
            assert text.endswith("\n") and "\n\n" not in text
            self.chunk_sizes.append(len(raw))
            for ln in text[:-1].split("\n"):
                assert len(ln.encode("utf-8")) <= migrate.LINE_MAX_BYTES
                it = json.loads(ln)
                b = _server_jcs(it)
                p["rows"].append({"seq": len(p["rows"]), "original_id": it["original_id"], "source_revision": it["source_revision"],
                                  "unit_kind": it["unit_kind"], "content_hash": it["content_hash"], "sha": _sha(b),
                                  "payload": it, "action": None, "reason": None})
                p["item_count"] += 1
                p["staged_bytes"] += len(b)
            return 200, {"plan_id": pid, "received": p["item_count"], "staged_bytes": p["staged_bytes"]}, {}
        if op == "seal" and method == "POST":
            n = json.loads(raw)["item_count"]
            if n != p["item_count"]:
                return self.err(409, "PLAN-COUNT-MISMATCH", received=p["item_count"])
            for x in p["rows"]:
                rv = (x["payload"].get("review") or {}).get("state")
                if x["unit_kind"] != "source" and rv != "reviewed":
                    x["action"], x["reason"] = "reject", "review_pending"
                else:
                    x["action"] = "insert"
            p["plan_hash"] = _sha(_server_jcs([x["sha"] for x in p["rows"]]))
            p["state"] = "sealed"
            return 200, self._plan_out(p), {}
        if op == "cancel" and method == "POST":
            p["state"] = "cancelled"
            return 200, self._plan_out(p), {}
        if op == "receipt" and method == "GET":
            if p["state"] != "applied":
                return self.err(409, "PLAN-STATE", state=p["state"])
            return 200, p["receipt"], {}
        return self.err(404, "NOT-FOUND")

    def apply(self, pid):
        """웹 [반영] 흉내 — insert = applied(stored_hash = content_hash), reject = skipped_reject."""
        p = self.plans[pid]
        items, res, units = [], {}, {}
        for x in p["rows"]:
            ok = x["action"] == "insert"
            r = "applied" if ok else "skipped_" + x["action"]
            items.append({"seq": x["seq"], "original_id": x["original_id"], "source_revision": x["source_revision"],
                          "unit_kind": x["unit_kind"], "target_kind": "record", "content_hash": x["content_hash"], "result": r,
                          "target_id": f"t_{x['seq']}" if ok else None, "stored_hash": x["content_hash"] if ok else None,
                          "target_state": "live" if ok else None})
            res[r] = res.get(r, 0) + 1
            units.setdefault(x["unit_kind"], {})
            units[x["unit_kind"]][r] = units[x["unit_kind"]].get(r, 0) + 1
        rh = _sha(_server_jcs([[i["original_id"], i["source_revision"], i["content_hash"], i["result"], i["target_id"]] for i in items]))
        p["state"] = "applied"
        p["receipt"] = {"plan_id": pid, "import_batch_id": pid, "plan_hash": p["plan_hash"], "receipt_hash": rh,
                        "applied_at": "2026-11-02T12:00:00+09:00", "counts": {"results": res, "units": units}, "items": items}


# ── 정규화 · 해시 ──────────────────────────────────────────

@unittest.skipUnless(os.path.exists(VEC), "공용 정규화 벡터 없음(키트 단독 배포)")
class NormalizeVectorsTest(unittest.TestCase):
    def test_all_shared_vectors(self):
        with open(VEC, encoding="utf-8") as f:
            v = json.load(f)
        self.assertEqual(v["contract"], migrate.CONTRACT)
        self.assertEqual(len(v["vectors"]), 18)
        for x in v["vectors"]:
            with self.subTest(x["name"]):
                self.assertEqual(migrate.normalize(x["input"]), x["normalized"])
                self.assertEqual(migrate.content_hash(x["input"]), x["sha256"])


class HashTest(unittest.TestCase):
    def test_jcs_matches_contract_formula(self):
        v = {"b": [1, "한글", None, True], "a": {"z": "é", "y": 0}, "𝒳": 1, "Ａ": 2}   # 아스트랄 키 — code point 정렬
        self.assertEqual(migrate.jcs(v), _server_jcs(v))

    def test_item_plan_receipt_hash(self):
        items = [rec(1), rec(2)]
        shas = [_sha(_server_jcs(i)) for i in items]
        self.assertEqual([migrate.item_sha256(i) for i in items], shas)
        self.assertEqual(migrate.plan_hash_of(shas), _sha(_server_jcs(shas)))
        rows = [{"original_id": "o_" + "1" * 32, "source_revision": "v_" + "2" * 32, "content_hash": "3" * 64, "result": "applied",
                 "target_id": "r_1"},
                {"original_id": "o_" + "4" * 32, "source_revision": "v_" + "5" * 32, "content_hash": "6" * 64,
                 "result": "skipped_reject", "target_id": None}]
        want = _sha(_server_jcs([[r["original_id"], r["source_revision"], r["content_hash"], r["result"], r["target_id"]] for r in rows]))
        self.assertEqual(migrate.receipt_hash_of(rows), want)

    def test_recommended_ids(self):
        oid = migrate.recommended_original_id("pc-1", "career/decisions.md", "#d-01")
        self.assertEqual(oid, "o_" + _sha("pc-1\ncareer/decisions.md\n#d-01".encode("utf-8"))[:32])
        it = {"original_id": oid, "unit_kind": "record", "body": "x", "source_revision": "v_" + "0" * 32}
        self.assertEqual(migrate.recommended_source_revision(it),
                         "v_" + _sha(_server_jcs({k: v for k, v in it.items() if k != "source_revision"}))[:32])

    def test_prepare_fills_hash_then_revision(self):
        out = migrate.prepare([(1, rec(1)), (2, src(1))], SI)
        r, s = out
        self.assertEqual(r["source_instance"], SI)
        self.assertEqual(r["content_hash"], migrate.content_hash(rec(1)["body"]))
        self.assertEqual(s["content_hash"], migrate.content_hash("합성 출처 1"))
        # source_revision 은 content_hash 까지 채운 항목으로 계산
        self.assertEqual(r["source_revision"], migrate.recommended_source_revision(r))
        self.assertIn("content_hash", {k for k in r if k != "source_revision"})
        # 입력에 있으면 그대로 둔다
        given = rec(3, source_revision="v_" + "a" * 32)
        self.assertEqual(migrate.prepare([(1, given)], SI)[0]["source_revision"], "v_" + "a" * 32)


class InputCheckTest(unittest.TestCase):
    def _rule(self, items, si=SI):
        with self.assertRaises(migrate.InputError) as cm:
            migrate.prepare([(i + 1, x) for i, x in enumerate(items)], si)
        return cm.exception.rule

    def test_owner_fields_rejected_locally(self):
        for k in migrate.OWNER_KEYS:
            with self.subTest(k):
                self.assertEqual(self._rule([rec(1, **{k: "u_1"})]), "owner_field_not_allowed")

    def test_original_id_required_and_unique(self):
        it = rec(1)
        del it["original_id"]
        self.assertEqual(self._rule([it]), "required")
        self.assertEqual(self._rule([rec(1, original_id="o_short")]), "format")
        self.assertEqual(self._rule([rec(1), rec(2, original_id=rec(1)["original_id"])]), "duplicate_in_plan")

    def test_hash_mismatch_and_limits(self):
        self.assertEqual(self._rule([rec(1, content_hash="0" * 64)]), "content_hash_mismatch")
        self.assertEqual(self._rule([rec(1, body="가" * (migrate.BODY_MAX_BYTES // 3 + 1))]), "too_long_bytes")
        self.assertTrue(self._rule([rec(i) for i in range(migrate.PLAN_MAX_ITEMS + 1)]).startswith("too_many_items"))
        self.assertEqual(self._rule([rec(1, unit_kind="nope")]), "enum")
        self.assertEqual(self._rule([rec(1, body="a\x00b")]), "invalid_char")
        # 본문은 64KB 안이지만 줄(JCS) 이 96KB 를 넘는다
        big = rec(1, fields={"k": "x" * (migrate.LINE_MAX_BYTES)})
        self.assertTrue(self._rule([big]).startswith("line_too_long_bytes"))

    def test_json_rules(self):
        for text, rule in (('{"a":1.5}', "float_not_allowed"), ('{"a":NaN}', "nan_not_allowed"), ('{"a":1,"a":2}', "duplicate_key"),
                           ("[1]", "object_required"), ("{", "json")):
            with self.subTest(text):
                with self.assertRaises(migrate.InputError) as cm:
                    migrate.parse_line(text, 1)
                self.assertEqual(cm.exception.rule, rule)

    def test_source_instance(self):
        raw = [(1, rec(1)), (2, rec(2, source_instance="pc-other"))]
        self.assertEqual(migrate.plan_instance([(1, rec(1, source_instance="pc-a"))], None), "pc-a")
        with self.assertRaises(migrate.InputError):
            migrate.plan_instance(raw, "pc-a")
        with self.assertRaises(migrate.InputError) as cm:
            migrate.plan_instance([(1, rec(1))], None)
        self.assertEqual(cm.exception.rule, "missing")


class ChunkTest(unittest.TestCase):
    def test_boundaries(self):
        C = migrate.CHUNK_MAX_BYTES
        # 4줄 × (64KB − 1) + 개행 4 = 정확히 256KB → 한 청크
        lines = [b"x" * (64 * 1024 - 1)] * 4
        self.assertEqual(sum(len(x) + 1 for x in lines), C)
        self.assertEqual(migrate.chunks(lines), [(0, 4)])
        # 1바이트 더 → 나뉜다
        lines2 = [b"x" * (64 * 1024)] + [b"x" * (64 * 1024 - 1)] * 3
        self.assertEqual(migrate.chunks(lines2), [(0, 3), (3, 4)])
        # 96KB 줄 셋 = 288KB → 2 + 1
        self.assertEqual(migrate.chunks([b"y" * migrate.LINE_MAX_BYTES] * 3), [(0, 2), (2, 3)])
        for s, e in migrate.chunks([b"z" * 1000] * 600):
            self.assertLessEqual(sum(1001 for _ in range(s, e)), C)

    def test_line_exactly_96kb_allowed(self):
        it = rec(1)
        base = len(migrate.jcs(migrate.prepare([(1, dict(it, fields={"k": ""}))], SI)[0]))
        fill = migrate.LINE_MAX_BYTES - base
        out = migrate.prepare([(1, dict(it, fields={"k": "x" * fill}))], SI)
        self.assertEqual(len(migrate.jcs(out[0])), migrate.LINE_MAX_BYTES)


class UploadResumeTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeServer()
        self.cl = migrate.Client(self.srv.url, TOKEN)

    def tearDown(self):
        self.srv.close()

    def test_chunk_offset_resume_from_received(self):
        items = migrate.prepare([(i + 1, rec(i, body=f"{BODY_MARK} {i} " + "가" * 20000)) for i in range(20)], SI)
        lines = [migrate.jcs(i) for i in items]
        pid = self.cl.create_plan(SI)["plan_id"]
        # 앞 실행이 첫 청크를 보냈는데 응답을 못 받은 상황 — 서버엔 이미 k개
        k = migrate.chunk_end(lines, 0)
        self.cl.upload(pid, 0, b"".join(x + b"\n" for x in lines[:k]))
        msgs = []
        got = migrate.upload_all(self.cl, pid, lines, msgs.append)
        self.assertEqual(got, 20)
        self.assertEqual([x["original_id"] for x in self.srv.plans[pid]["rows"]], [i["original_id"] for i in items])
        self.assertTrue(any(str(k) in m for m in msgs))
        self.assertTrue(all(s <= migrate.CHUNK_MAX_BYTES for s in self.srv.chunk_sizes))
        self.assertGreater(len(self.srv.chunk_sizes), 2)
        pl = self.cl.seal(pid, 20)
        self.assertEqual(pl["plan_hash"], migrate.plan_hash_of(migrate.sha256_hex(x) for x in lines))

    def test_network_drop_resumes_from_status(self):
        class Flaky:
            def __init__(self, real):
                self.real, self.n = real, 0

            def upload(self, pid, off, raw):
                self.n += 1
                r = self.real.upload(pid, off, raw)
                if self.n == 1:
                    raise migrate.NetworkError("timeout")   # 서버엔 들어갔고 응답만 끊김
                return r

            def status(self, pid):
                return self.real.status(pid)

        items = migrate.prepare([(i + 1, rec(i, body="나" * 20000)) for i in range(12)], SI)
        lines = [migrate.jcs(i) for i in items]
        pid = self.cl.create_plan(SI)["plan_id"]
        self.assertEqual(migrate.upload_all(Flaky(self.cl), pid, lines), 12)
        self.assertEqual(len(self.srv.plans[pid]["rows"]), 12)

    def test_count_mismatch_detail(self):
        pid = self.cl.create_plan(SI)["plan_id"]
        with self.assertRaises(migrate.ApiError) as cm:
            self.cl.seal(pid, 3)
        self.assertEqual((cm.exception.code, cm.exception.detail.get("received")), ("PLAN-COUNT-MISMATCH", 0))


class VerifyUnitTest(unittest.TestCase):
    def _receipt(self, items):
        srv = FakeServer()
        try:
            cl = migrate.Client(srv.url, TOKEN)
            pid = cl.create_plan(SI)["plan_id"]
            migrate.upload_all(cl, pid, [migrate.jcs(i) for i in items])
            cl.seal(pid, len(items))
            srv.apply(pid)
            return cl.receipt(pid)
        finally:
            srv.close()

    def test_match_and_mismatches(self):
        items = migrate.prepare([(1, rec(1)), (2, rec(2, review={"state": "pending"})), (3, src(1))], SI)
        rc = self._receipt(items)
        self.assertTrue(migrate.verify(rc, items)["ok"])
        # stored_hash 가 다르다(서버 본문이 바뀜)
        bad = json.loads(json.dumps(rc))
        bad["items"][0]["stored_hash"] = "f" * 64
        probs = migrate.verify(bad, items)["problems"]
        self.assertIn((0, items[0]["original_id"], "stored_hash_mismatch"), probs)
        # 휴지통 — stored_hash null
        bad = json.loads(json.dumps(rc))
        bad["items"][2].update(stored_hash=None, target_state="trashed")
        self.assertIn((2, items[2]["original_id"], "stored_trashed"), migrate.verify(bad, items)["problems"])
        # skipped 항목은 stored_hash 를 보지 않는다
        self.assertEqual(rc["items"][1]["result"], "skipped_reject")
        # 입력 쪽이 다르다(source_revision)
        other = [dict(items[0], source_revision="v_" + "9" * 32)] + items[1:]
        res = migrate.verify(rc, other)
        self.assertIn((0, items[0]["original_id"], "source_revision_mismatch"), res["problems"])
        self.assertFalse(res["receipt_hash_ok"])
        # 자료군 개수 — counts.units 변조
        bad = json.loads(json.dumps(rc))
        bad["counts"]["units"]["record"]["applied"] += 1
        self.assertIn((None, None, "unit_count_mismatch:record"), migrate.verify(bad, items)["problems"])
        # 항목 하나 빠짐
        bad = json.loads(json.dumps(rc))
        bad["items"].pop()
        self.assertIn((2, items[2]["original_id"], "missing_in_receipt"), migrate.verify(bad, items)["problems"])
        # receipt_hash 변조
        bad = dict(rc, receipt_hash="0" * 64)
        self.assertIn((None, None, "receipt_hash_mismatch"), migrate.verify(bad, items)["problems"])


# ── CLI ────────────────────────────────────────────────────

class RecordingRunner:
    """MacKeychain 용 — argv·stdin 기록, 메모리에 저장."""

    def __init__(self):
        self.calls, self.store = [], {}

    def __call__(self, argv, stdin_text=None, timeout=30):
        import re
        import subprocess
        self.calls.append((list(argv), stdin_text))
        if argv[1:2] == ["-i"]:
            m = re.search(r'-a "([^"]+)" -w "([^"]+)"', stdin_text)
            self.store[m.group(1)] = m.group(2)
            return subprocess.CompletedProcess(argv, 0, "", "")
        acct = argv[argv.index("-a") + 1]
        if argv[1] == "find-generic-password":
            if acct in self.store:
                return subprocess.CompletedProcess(argv, 0, self.store[acct] + "\n", "")
            return subprocess.CompletedProcess(argv, 44, "", "")
        if argv[1] == "delete-generic-password":
            return subprocess.CompletedProcess(argv, 0 if self.store.pop(acct, None) else 44, "", "")
        raise AssertionError(argv)


class CliFlowTest(unittest.TestCase):
    def setUp(self):
        self.h = TempHome()
        self.srv = FakeServer()
        self.ks = MemoryKeyStore()
        self.tmp = tempfile.mkdtemp(prefix="mcrm-mig-")
        self.items_path = os.path.join(self.tmp, "items.jsonl")

    def tearDown(self):
        self.srv.close()
        self.h.cleanup()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv, stdin=""):
        out = io.StringIO()
        code = cli.main(["--home", self.h.home, "migrate", *argv], ks_factory=lambda s, r=None: self.ks, out=out,
                        stdin=io.StringIO(stdin), getpass_fn=lambda p: "")
        return code, out.getvalue()

    def login(self):
        code, out = self.run_cli("login", "--server", self.srv.url, "--token-stdin", stdin=TOKEN + "\n")
        self.assertEqual(code, 0, out)
        return out

    def test_full_flow_stage_receipt_verify(self):
        outs = [self.login()]
        self.assertEqual(self.ks.items[migrate.token_account(self.srv.url)], TOKEN)
        write_jsonl(self.items_path, [rec(1), rec(2), rec(3, review={"state": "pending"}), src(1)])
        code, out = self.run_cli("stage", self.items_path, "--server", self.srv.url, "--source-instance", SI)
        outs.append(out)
        self.assertEqual(code, 0, out)
        pid = next(iter(self.srv.plans))
        self.assertIn(f"plan_id: {pid}", out)
        self.assertIn("reject 사유: review_pending 1", out)
        self.assertIn("insert 3", out)
        self.assertIn("로컬 계산과 일치", out)
        code, out = self.run_cli("status", pid, "--server", self.srv.url)
        outs.append(out)
        self.assertEqual(code, 0)
        self.assertIn("상태 sealed", out)
        # 반영 전 영수증 = 409 PLAN-STATE
        code, out = self.run_cli("receipt", pid, "--server", self.srv.url)
        self.assertEqual(code, 1)
        self.assertIn("PLAN-STATE", out)
        self.srv.apply(pid)
        code, out = self.run_cli("receipt", pid, "--server", self.srv.url, "--verify", self.items_path)
        outs.append(out)
        self.assertEqual(code, 0, out)
        self.assertIn("결과: 일치", out)
        self.assertIn("applied 3", out)
        # 서버 본문이 바뀌었다 → 1, 출력엔 seq·original_id·사유만
        self.srv.plans[pid]["receipt"]["items"][1]["stored_hash"] = "e" * 64
        code, out = self.run_cli("receipt", pid, "--server", self.srv.url, "--verify", self.items_path)
        outs.append(out)
        self.assertEqual(code, 1)
        self.assertIn(f"seq=1 original_id={rec(2)['original_id']} stored_hash_mismatch", out)
        # 입력 파일을 고쳤다 → content_hash·source_revision 불일치
        write_jsonl(self.items_path, [rec(1, body="바뀐 합성 본문"), rec(2), rec(3, review={"state": "pending"}), src(1)])
        code, out = self.run_cli("receipt", pid, "--server", self.srv.url, "--verify", self.items_path)
        outs.append(out)
        self.assertEqual(code, 1)
        self.assertIn("content_hash_mismatch", out)
        code, out = self.run_cli("logout", "--server", self.srv.url)
        outs.append(out)
        self.assertNotIn(migrate.token_account(self.srv.url), self.ks.items)
        for o in outs:
            self.assertNotIn(TOKEN, o)
            self.assertNotIn(BODY_MARK, o)
            self.assertNotIn("둘째 줄", o)

    def test_cancel(self):
        self.login()
        write_jsonl(self.items_path, [rec(1)])
        self.assertEqual(self.run_cli("stage", self.items_path, "--server", self.srv.url, "--source-instance", SI)[0], 0)
        pid = next(iter(self.srv.plans))
        code, out = self.run_cli("cancel", pid, "--server", self.srv.url)
        self.assertEqual(code, 0)
        self.assertIn("cancelled", out)

    def test_owner_field_rejected_before_any_request(self):
        self.login()
        write_jsonl(self.items_path, [rec(1), rec(2, user_id="u_someone")])
        code, out = self.run_cli("stage", self.items_path, "--server", self.srv.url, "--source-instance", SI)
        self.assertEqual(code, 1)
        self.assertIn("2번째 줄 $.user_id: owner_field_not_allowed", out)
        self.assertEqual(self.srv.requests, [])

    def test_429_reports_retry_after_without_retry(self):
        self.login()
        write_jsonl(self.items_path, [rec(1)])
        self.srv.force[("POST", "plans")] = (429, {"code": "PLAN-LIMIT", "msg": "열린 이관 plan 은 3개까지예요."}, {"retry-after": "17"})
        code, out = self.run_cli("stage", self.items_path, "--server", self.srv.url, "--source-instance", SI)
        self.assertEqual(code, 1)
        self.assertIn("http-429 PLAN-LIMIT", out)
        self.assertIn("17초 뒤에 다시 실행하세요", out)
        self.assertEqual(len(self.srv.requests), 1)

    def test_error_messages(self):
        self.login()
        pid = "mp_" + "0" * 24
        for status, code, want in ((410, "PLAN-EXPIRED", "만료"), (503, "MIGRATION-OFF", "스위치"),
                                   (401, "TOKEN-REVOKED", "migrate login"), (404, "NOT-FOUND", "plan 이 없어요")):
            with self.subTest(code):
                self.srv.force[("GET", "plan")] = (status, {"code": code, "msg": "합성"}, {})
                c, out = self.run_cli("status", pid, "--server", self.srv.url)
                self.assertEqual(c, 1)
                self.assertIn(f"http-{status} {code}", out)
                self.assertIn(want, out)

    def test_usage_and_missing_token(self):
        self.assertEqual(self.run_cli("status", "nope", "--server", self.srv.url)[0], 2)
        self.assertEqual(self.run_cli("status", "mp_" + "0" * 24, "--server", "http://example.invalid")[0], 2)
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("receipt", "mp_" + "0" * 24)   # --server 빠짐
        self.assertEqual(cm.exception.code, 2)
        code, out = self.run_cli("status", "mp_" + "0" * 24, "--server", self.srv.url)
        self.assertEqual(code, 1)
        self.assertIn("migrate login", out)
        code, out = self.run_cli("login", "--server", self.srv.url, "--token-stdin", stdin="imp_wrong\n")
        self.assertEqual(code, 2)
        self.assertEqual(self.ks.items, {})

    def test_no_token_flag_in_parser(self):
        p = cli._parser()
        sub = next(a for a in p._actions if a.dest == "cmd").choices["migrate"]
        msub = next(a for a in sub._actions if a.dest == "mcmd")
        for name, sp in msub.choices.items():
            for act in sp._actions:
                for opt in act.option_strings:
                    self.assertNotIn(opt, ("--token", "-t"), name)

    def test_token_not_in_keychain_argv(self):
        runner = RecordingRunner()
        out = io.StringIO()
        code = cli.main(["--home", self.h.home, "migrate", "login", "--server", self.srv.url, "--token-stdin"],
                        ks_factory=lambda s, r=None: keystore.MacKeychain(s, runner), out=out, stdin=io.StringIO(TOKEN + "\n"))
        self.assertEqual(code, 0)
        self.assertTrue(runner.calls)
        for argv, stdin_text in runner.calls:
            self.assertFalse(any(TOKEN in x for x in argv))
        self.assertTrue(any(stdin_text and TOKEN in stdin_text for _a, stdin_text in runner.calls))
        self.assertEqual(runner.store[migrate.token_account(self.srv.url)], TOKEN)
        self.assertNotIn(TOKEN, out.getvalue())
        acct = migrate.token_account(self.srv.url)
        self.assertTrue(acct.startswith("migration-token:127.0.0.1:"))
        self.assertTrue(keystore._SAFE.match(acct))

    def test_missing_module_in_installed_bundle(self):
        import sys
        from unittest import mock
        import agent
        saved = agent.__dict__.pop("migrate")   # 설치 패키지처럼 모듈이 없을 때
        try:
            with mock.patch.dict(sys.modules, {"agent.migrate": None}):
                code, out = self.run_cli("status", "mp_" + "0" * 24, "--server", self.srv.url)
        finally:
            agent.migrate = saved
        self.assertEqual(code, 2)
        self.assertIn("키트 루트에서 파이썬으로 실행하세요", out)

    def test_client_repr_hides_token(self):
        self.assertNotIn(TOKEN, repr(migrate.Client("https://x.invalid", TOKEN)))


if __name__ == "__main__":
    unittest.main()
