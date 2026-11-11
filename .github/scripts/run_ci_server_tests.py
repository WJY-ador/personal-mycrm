"""대화 관련 서버 시험을 격리하고 가드한 시험 DB로 CI에서 돌린다.

PR 54(커밋 6c1b199)의 러너를 main에 맞게 줄인 것이다. main에 있는 시험 파일만 넣는다.
  unit      DB 없는 시험 7개(승인 HTTP, 확인 카드, MCP 게이트웨이 셋, 동의 서명, 트랜잭션 범위)
  approvals 대화 승인 DB 시험 1개(crm_test_chat_approvals를 새로 만들어 돌린다)
  injection 대화 주입 DB 시험 1개(crm_test_chat_injection, 2026-11-11 대화 하나로 F)
넣지 않은 것: test_freechat_synthetic_e2e(darwin 전용 공급자와 macOS 잡이 필요), test_migration_mcp(test_migration_path가 부른다),
test_user_change_marker_*(대화가 아니다).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[2]
UNIT_TESTS = (
    "test_chat_approval_http.py", "test_chat_confirmation_gate.py",
    "test_chat_mcp_gateway.py", "test_chat_mcp_route.py", "test_chat_mcp.py",
    "test_consent_signature.py", "test_db_tx_scope.py",
)
DB_TESTS = {
    "approvals": ("crm_test_chat_approvals", ("test_chat_approvals.py",)),
    "injection": ("crm_test_chat_injection", ("test_chat_injection.py",)),
}


def guarded_database_url(url: str, expected_db: str, expected_port: int) -> str:
    """Reject all but the exact local, dedicated PostgreSQL CI database."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid test database URL") from exc
    if (parts.scheme not in {"postgres", "postgresql"}
            or parts.hostname not in {"localhost", "127.0.0.1"}
            or port != expected_port or parts.path != "/" + expected_db
            or not expected_db.startswith("crm_test_")
            or parts.query or parts.fragment):
        raise ValueError("refusing non-local or unexpected test database")
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))


def verify_result(filename: str, output: str) -> None:
    if filename == "test_consent_signature.py":
        if not re.search(r"(?m)^전부 통과\([1-9]\d*건\)$", output):
            raise RuntimeError(f"{filename}: no completed signature checks")
    else:
        if not re.search(r"(?m)^Ran [1-9]\d* tests? in ", output):
            raise RuntimeError(f"{filename}: no tests executed")
        if not re.search(r"(?m)^OK\s*$", output) or re.search(r"(?mi)^.*\bskipped\b.*$", output):
            raise RuntimeError(f"{filename}: incomplete or skipped tests")


def run_test(filename: str, env: dict[str, str]) -> None:
    result = subprocess.run([sys.executable, str(ROOT / "server" / filename), "-v"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=300)
    print(f"--- {filename} ---", flush=True)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise RuntimeError(f"{filename} failed with exit code {result.returncode}")
    verify_result(filename, result.stdout)


def clear_libpq_environment(env) -> None:
    """Remove libpq defaults before both the admin connection and child tests.

    In particular, PGHOSTADDR can override the address used for a URL whose
    hostname is localhost, so validating the URL alone is not sufficient.
    """
    for key in tuple(env):
        if key.startswith("PG"):
            del env[key]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("unit", *DB_TESTS))
    parser.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    # psycopg.connect below reads the current process environment too; only
    # cleaning the child environment would leave the admin connection exposed.
    clear_libpq_environment(os.environ)
    env = os.environ.copy()
    if args.case == "unit" and shutil.which("node", path=env.get("PATH")) is None:
        raise RuntimeError("Node.js is required for the consent signature test")
    if args.case == "unit":
        # These are synthetic tests, including test_db_tx_scope's fake pool.
        # Remove libpq defaults too so an accidental connection cannot inherit one.
        env["DATABASE_URL"] = ""
        for filename in UNIT_TESTS:
            run_test(filename, env)
        return

    database, filenames = DB_TESTS[args.case]
    url = env.get("DATABASE_URL", "")
    admin_url = guarded_database_url(url, database, args.port)
    # A fresh CI service is required. Never drop or reuse an existing database.
    import psycopg
    from psycopg import sql
    with psycopg.connect(admin_url, autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone():
            raise RuntimeError("dedicated test database already exists; refusing to reuse it")
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    for filename in filenames:
        guarded_database_url(env.get("DATABASE_URL", ""), database, args.port)
        run_test(filename, env)


if __name__ == "__main__":
    main()
