"""Synthetic transaction-scope semantics; no database or connection pool."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch

import db


class FakeConnection:
    def __init__(self):
        self.events = []

    @contextmanager
    def transaction(self):
        depth = sum(1 for event in self.events if event[0] == "begin") - sum(
            1 for event in self.events if event[0] in ("commit", "rollback")
        )
        self.events.append(("begin", depth))
        try:
            yield self
        except BaseException:
            self.events.append(("rollback", depth))
            raise
        else:
            self.events.append(("commit", depth))


class FakePool:
    def __init__(self, connection):
        self.conn = connection
        self.opens = 0

    @contextmanager
    def connection(self):
        self.opens += 1
        yield self.conn


class TxScopeTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        self.pool = FakePool(self.conn)
        self.patch = patch("db.pool", return_value=self.pool)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_nested_scope_and_tx_reuse_same_connection_with_savepoints(self):
        with db.tx_scope() as outer:
            with db.tx() as one:
                self.assertIs(one, outer)
            with db.tx_scope() as nested:
                self.assertIs(nested, outer)
                with db.tx() as two:
                    self.assertIs(two, outer)
        self.assertEqual(self.pool.opens, 1)
        self.assertEqual([event[0] for event in self.conn.events], [
            "begin", "begin", "commit", "begin", "begin", "commit", "commit", "commit",
        ])

    def test_caught_nested_failure_rolls_back_savepoint_only(self):
        with db.tx_scope() as outer:
            with self.assertRaisesRegex(ValueError, "synthetic"):
                with db.tx_scope():
                    raise ValueError("synthetic")
            with db.tx() as c:
                self.assertIs(c, outer)
        self.assertEqual([event[0] for event in self.conn.events], [
            "begin", "begin", "rollback", "begin", "commit", "commit",
        ])

    def test_uncaught_nested_failure_aborts_outer_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with db.tx_scope():
                with db.tx_scope():
                    raise RuntimeError("abort")
        self.assertEqual([event[0] for event in self.conn.events], [
            "begin", "begin", "rollback", "rollback",
        ])


if __name__ == "__main__":
    unittest.main()
