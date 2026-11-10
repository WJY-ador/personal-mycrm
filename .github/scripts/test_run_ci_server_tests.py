"""Safety and execution checks for the isolated server CI test runner."""
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "run_ci_server_tests", Path(__file__).with_name("run_ci_server_tests.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ServerCiRunnerTests(unittest.TestCase):
    def test_guard_accepts_only_exact_dedicated_local_database(self):
        expected = "crm_test_chat_approvals"
        self.assertEqual(
            runner.guarded_database_url("postgresql://localhost:5432/" + expected, expected, 5432),
            "postgresql://localhost:5432/postgres",
        )
        for url in ("", "postgresql://remote:5432/" + expected,
                    "postgresql://localhost:5433/" + expected,
                    "postgresql://localhost:5432/crm",
                    "postgresql://localhost:5432/" + expected + "?host=remote",
                    "postgresql://localhost:5432/" + expected + "_other"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                runner.guarded_database_url(url, expected, 5432)

    def test_zero_or_skipped_unittest_is_rejected(self):
        for output in ("Ran 0 tests in 0.001s\nOK\n", "Ran 2 tests in 0.001s\nOK (skipped=1)\n",
                       "test_something ... skipped 'missing DB'\nRan 1 test in 0.001s\nOK (skipped=1)\n"):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                runner.verify_result("test_db_tx_scope.py", output)
        runner.verify_result("test_db_tx_scope.py", "Ran 3 tests in 0.001s\n\nOK\n")

    def test_non_unittest_scripts_need_their_completion_marker(self):
        with self.assertRaises(RuntimeError):
            runner.verify_result("test_consent_signature.py", "")
        with self.assertRaises(RuntimeError):
            runner.verify_result("test_consent_signature.py", "전부 통과(0건)\n")
        runner.verify_result("test_consent_signature.py", "전부 통과(19건)\n")

    def test_eight_modules_are_registered_once_and_exist(self):
        modules = list(runner.UNIT_TESTS)
        for _database, filenames in runner.DB_TESTS.values():
            modules.extend(filenames)
        self.assertEqual(len(modules), 8)
        self.assertEqual(len(set(modules)), 8)
        for name in modules:
            self.assertTrue((runner.ROOT / "server" / name).is_file(), name)

    def test_hostile_libpq_environment_is_cleared_for_admin_and_children(self):
        observed = []

        class Connection:
            def __enter__(self):
                observed.append(("admin", dict(os.environ)))
                return self

            def __exit__(self, *args):
                pass

            def execute(self, _query, *_args):
                return SimpleNamespace(fetchone=lambda: None)

        class Query:
            def format(self, _identifier):
                return self

        fake_sql = SimpleNamespace(SQL=lambda _query: Query(), Identifier=lambda value: value)
        fake_psycopg = SimpleNamespace(connect=lambda *_args, **_kwargs: Connection(), sql=fake_sql)
        hostile = {
            "DATABASE_URL": "postgresql://localhost:5432/crm_test_chat_approvals",
            "PGHOSTADDR": "203.0.113.1", "PGSERVICE": "foreign-service",
            "PGOPTIONS": "-c search_path=wrong", "KEEP": "yes",
        }
        with patch.dict(os.environ, hostile, clear=True), \
                patch.object(sys, "argv", ["runner", "approvals"]), \
                patch.dict(sys.modules, {"psycopg": fake_psycopg}), \
                patch.object(runner, "run_test", side_effect=lambda _name, env: observed.append(("child", env.copy()))):
            runner.main()

        self.assertEqual([kind for kind, _ in observed], ["admin", "child"])
        for _kind, env in observed:
            self.assertEqual(env["KEEP"], "yes")
            self.assertFalse(any(key.startswith("PG") for key in env))

    def test_missing_node_fails_before_any_unit_test_runs(self):
        with patch.dict(os.environ, {"PATH": ""}, clear=True), \
                patch.object(sys, "argv", ["runner", "unit"]), \
                patch.object(runner, "run_test", side_effect=AssertionError("must not run")), \
                self.assertRaisesRegex(RuntimeError, "Node.js is required"):
            runner.main()


if __name__ == "__main__":
    unittest.main()
