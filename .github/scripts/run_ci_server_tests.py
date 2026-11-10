"""Run the server CI suites with isolated, explicitly guarded test databases."""
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
    "migration": ("crm_test_migration_mcp", ("test_migration_mcp.py",)),
    "marker": ("crm_test_user_change_marker", (
        "test_user_change_marker_concurrency.py", "test_user_change_marker_coverage.py",
        "test_user_change_marker_production.py",
    )),
    "freechat": ("crm_test_freechat_e2e", ("test_freechat_synthetic_e2e.py",)),
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
    elif filename == "test_migration_mcp.py":
        if "이관 MCP(가안 X) 시험 전부 통과" not in output:
            raise RuntimeError(f"{filename}: migration checks did not complete")
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
    if args.case in {"unit", "freechat"} and shutil.which("node", path=env.get("PATH")) is None:
        raise RuntimeError("Node.js is required for the consent signature and freechat tests")
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
    if args.case == "marker":
        env["CRM_TEST_DB_PORT"] = str(args.port)
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
