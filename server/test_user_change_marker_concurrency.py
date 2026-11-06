"""합성 PostgreSQL 동시성 시험. 고유 로컬 DB만 허용하고 .env는 읽지 않는다."""
from __future__ import annotations

import os
import threading
import time
import unittest
from urllib.parse import urlparse

import psycopg
from psycopg.errors import DeadlockDetected


DATABASE_URL = os.environ.get("DATABASE_URL", "")
parsed = urlparse(DATABASE_URL)
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL을 명시하세요. 고유 로컬 시험 DB만 허용합니다.")
if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != int(os.environ.get("CRM_TEST_DB_PORT", "55439")) or parsed.path != "/crm_test_user_change_marker":
    raise SystemExit(f"시험 거부: host=127.0.0.1, port={os.environ.get('CRM_TEST_DB_PORT', '55439')}, db=crm_test_user_change_marker 만 허용합니다.")


class MarkerConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS marker_test_events")
            conn.execute("DROP TABLE IF EXISTS marker_test_users")
            conn.execute("CREATE TABLE marker_test_events (id bigserial PRIMARY KEY, user_id text NOT NULL)")
            conn.execute("CREATE TABLE marker_test_users (user_id text PRIMARY KEY, revision bigint NOT NULL DEFAULT 0)")
            conn.execute("INSERT INTO marker_test_users(user_id) VALUES ('a'), ('b')")

    def setUp(self):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute("TRUNCATE marker_test_events RESTART IDENTITY")
            conn.execute("UPDATE marker_test_users SET revision=0")

    def test_sequence_max_can_miss_a_later_commit(self):
        """ID 배정 순서는 커밋 순서가 아니므로 MAX(id)는 안전한 marker가 아니다."""
        with psycopg.connect(DATABASE_URL) as tx_a:
            tx_a_id = tx_a.execute("INSERT INTO marker_test_events(user_id) VALUES ('a') RETURNING id").fetchone()[0]
            with psycopg.connect(DATABASE_URL) as tx_b:
                tx_b_id = tx_b.execute("INSERT INTO marker_test_events(user_id) VALUES ('a') RETURNING id").fetchone()[0]
            self.assertGreater(tx_b_id, tx_a_id)
            with psycopg.connect(DATABASE_URL) as reader:
                observed = reader.execute("SELECT max(id) FROM marker_test_events WHERE user_id='a'").fetchone()[0]
            self.assertEqual(observed, tx_b_id)
        with psycopg.connect(DATABASE_URL) as reader:
            after_a_commits = reader.execute("SELECT max(id) FROM marker_test_events WHERE user_id='a'").fetchone()[0]
        self.assertEqual(after_a_commits, observed)
        self.assertNotEqual(tx_a_id, after_a_commits)

    def test_transactional_user_row_serializes_same_user_writers(self):
        """동일 사용자 marker UPDATE는 뒤 writer를 대기시켜 커밋 후 revision을 잇는다."""
        started = threading.Event()
        finished = threading.Event()
        errors: list[BaseException] = []

        def second_writer():
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    started.set()
                    conn.execute("UPDATE marker_test_users SET revision=revision+1 WHERE user_id='a'")
                finished.set()
            except BaseException as exc:  # propagate worker failures
                errors.append(exc)
                finished.set()

        with psycopg.connect(DATABASE_URL) as first:
            first.execute("UPDATE marker_test_users SET revision=revision+1 WHERE user_id='a'")
            worker = threading.Thread(target=second_writer)
            worker.start()
            self.assertTrue(started.wait(2))
            time.sleep(0.15)
            self.assertFalse(finished.is_set(), "두 번째 marker 갱신은 첫 트랜잭션 종료 전 진행하면 안 됩니다")
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors, errors)
        with psycopg.connect(DATABASE_URL) as reader:
            self.assertEqual(reader.execute("SELECT revision FROM marker_test_users WHERE user_id='a'").fetchone()[0], 2)

    def test_different_users_do_not_block_each_other(self):
        """사용자별 row 잠금은 다른 사용자의 marker 갱신을 막지 않는다."""
        with psycopg.connect(DATABASE_URL) as first:
            first.execute("UPDATE marker_test_users SET revision=revision+1 WHERE user_id='a'")
            with psycopg.connect(DATABASE_URL) as second:
                second.execute("SET LOCAL lock_timeout='250ms'")
                second.execute("UPDATE marker_test_users SET revision=revision+1 WHERE user_id='b'")

    def test_reverse_multistatement_user_lock_order_deadlocks(self):
        """per-user row만으로는 한 트랜잭션 안의 다중 statement 역순이 교착한다."""
        gate = threading.Barrier(2)
        outcomes: list[str] = []

        def writer(first_user, second_user):
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    conn.execute("SET LOCAL deadlock_timeout='100ms'")
                    conn.execute("UPDATE marker_test_users SET revision=revision+1 WHERE user_id=%s", (first_user,))
                    gate.wait(2)
                    conn.execute("UPDATE marker_test_users SET revision=revision+1 WHERE user_id=%s", (second_user,))
                outcomes.append("committed")
            except DeadlockDetected:
                outcomes.append("deadlock")

        writers = [threading.Thread(target=writer, args=("a", "b")), threading.Thread(target=writer, args=("b", "a"))]
        for writer_thread in writers:
            writer_thread.start()
        for writer_thread in writers:
            writer_thread.join(4)
        self.assertTrue(all(not writer_thread.is_alive() for writer_thread in writers))
        self.assertCountEqual(outcomes, ["committed", "deadlock"])


if __name__ == "__main__":
    unittest.main()
