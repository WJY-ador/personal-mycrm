"""합성 DB에 현재 운영 schema를 복사해 실험 trigger의 coverage를 검증한다. .env를 읽지 않는다."""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.errors import DeadlockDetected
from psycopg.rows import dict_row


DATABASE_URL = os.environ.get("DATABASE_URL", "")
parsed = urlparse(DATABASE_URL)
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL을 명시하세요. 고유 로컬 시험 DB만 허용합니다.")
if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != int(os.environ.get("CRM_TEST_DB_PORT", "55439")) or parsed.path != "/crm_test_user_change_marker":
    raise SystemExit(f"시험 거부: host=127.0.0.1, port={os.environ.get('CRM_TEST_DB_PORT', '55439')}, db=crm_test_user_change_marker 만 허용합니다.")

SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
import db  # noqa: E402 — DATABASE_URL 가드 이후 import

EXPERIMENT_SQL = (SERVER_DIR / "experiments" / "user_change_marker.sql").read_text(encoding="utf-8")
TRACKED = {
    "users", "profile", "questions", "tabs", "candidates", "candidate_history",
    "records", "record_history", "sources", "people", "source_reflections",
    "object_defs", "field_defs", "items", "item_links", "item_versions",
    "item_history", "item_stage", "confirm_events", "activities", "activity_links", "import_entries",
    "import_streams", "jobs", "stack_sessions", "std_marks", "std_choices", "optional_consents", "page_layouts",
}


class MarkerCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS marker_trial CASCADE")
            conn.execute("CREATE SCHEMA marker_trial")
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.row_factory = dict_row
            db.init_schema(conn)
            conn.execute(EXPERIMENT_SQL, prepare=False)

    def setUp(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("TRUNCATE users CASCADE")
            conn.execute("INSERT INTO users(id,email) VALUES ('u_a','a@synthetic.test'), ('u_b','b@synthetic.test')")

    def marker(self, user_id):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            row = conn.execute("SELECT revision FROM user_change_marker WHERE user_id=%s", (user_id,)).fetchone()
            return row[0] if row else None

    def test_trigger_catalog_covers_state_and_ui_tables(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            rows = conn.execute("SELECT c.relname, count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                                "WHERE NOT t.tgisinternal AND t.tgname LIKE 'marker_trial_%' "
                                "AND c.relname <> 'user_change_marker_pending' GROUP BY c.relname").fetchall()
        coverage = dict(rows)
        self.assertEqual(set(coverage), TRACKED)
        self.assertTrue(all(coverage[name] == 3 for name in TRACKED))

    def test_bulk_state_write_bumps_once_per_statement_and_user(self):
        before_a, before_b = self.marker("u_a"), self.marker("u_b")
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('q_a1','u_a','A1'), ('q_a2','u_a','A2'), "
                         "('q_b1','u_b','B1')")
        self.assertEqual(self.marker("u_a"), before_a + 1)
        self.assertEqual(self.marker("u_b"), before_b + 1)

    def test_insert_update_delete_each_advance_state_marker(self):
        start = self.marker("u_a")
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('q_events','u_a','before')")
        after_insert = self.marker("u_a")
        self.assertEqual(after_insert, start + 1)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("UPDATE questions SET text='after' WHERE id='q_events'")
        after_update = self.marker("u_a")
        self.assertEqual(after_update, after_insert + 1)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("DELETE FROM questions WHERE id='q_events'")
        self.assertEqual(self.marker("u_a"), after_update + 1)

    def test_device_heartbeat_is_time_derived_but_device_changes_are_tracked(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("INSERT INTO import_streams(user_id,id,channel,label) VALUES ('u_a','is_trial','board_migration','trial')")
        after_insert = self.marker("u_a")
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("UPDATE import_streams SET last_used_at=now() WHERE user_id='u_a' AND id='is_trial'")
        self.assertEqual(self.marker("u_a"), after_insert)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("UPDATE import_streams SET revoked_at=now() WHERE user_id='u_a' AND id='is_trial'")
        self.assertEqual(self.marker("u_a"), after_insert + 1)

    def test_global_job_sweep_updates_marker_for_each_affected_user(self):
        before_a, before_b = self.marker("u_a"), self.marker("u_b")
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.row_factory = dict_row
            conn.execute("INSERT INTO jobs(id,user_id,session_id,kind,status,expires_at) VALUES "
                         "('00000000-0000-0000-0000-000000000001','u_a','00000000-0000-0000-0000-000000000011',"
                         "'converse','queued',now()-interval '1 hour'), "
                         "('00000000-0000-0000-0000-000000000002','u_b','00000000-0000-0000-0000-000000000022',"
                         "'converse','queued',now()-interval '1 hour')")
            # job_get/job_assign/stack_enqueue call this global, multi-user transaction.
            db._job_sweep(conn)
        self.assertEqual(self.marker("u_a"), before_a + 1)  # one marker bump for this transaction
        self.assertEqual(self.marker("u_b"), before_b + 1)

    def test_rollback_reverts_business_rows_and_marker(self):
        before = self.marker("u_a")
        with self.assertRaises(RuntimeError):
            with psycopg.connect(DATABASE_URL) as conn:
                conn.execute("SET LOCAL search_path TO marker_trial")
                conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('q_rollback','u_a','temporary')")
                raise RuntimeError("synthetic rollback")
        self.assertEqual(self.marker("u_a"), before)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            self.assertIsNone(conn.execute("SELECT 1 FROM questions WHERE id='q_rollback'").fetchone())

    def test_user_delete_cascade_removes_owner_marker(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('q_delete','u_a','delete')")
            conn.execute("DELETE FROM users WHERE id='u_a'")
        self.assertIsNone(self.marker("u_a"))
        self.assertIsNotNone(self.marker("u_b"))

    def test_db_migration_is_idempotent_and_keeps_trigger_coverage(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.row_factory = dict_row
            db.init_schema(conn)
            conn.execute(EXPERIMENT_SQL, prepare=False)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            got = {r[0] for r in conn.execute("SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                                               "WHERE NOT t.tgisinternal AND t.tgname LIKE 'marker_trial_%' "
                                               "AND c.relname <> 'user_change_marker_pending'")}
        self.assertEqual(got, TRACKED)

    def test_reversed_multi_statement_multiuser_transactions_commit_in_order(self):
        barrier = threading.Barrier(2)
        result = []

        def writer(first, second):
            try:
                with psycopg.connect(DATABASE_URL) as conn:
                    conn.execute("SET LOCAL search_path TO marker_trial")
                    conn.execute("SET LOCAL deadlock_timeout='100ms'")
                    conn.execute("INSERT INTO questions(id,user_id,text) VALUES (%s,%s,'first')", (f'q_{first}_{second}_1', first))
                    barrier.wait(2)
                    conn.execute("INSERT INTO questions(id,user_id,text) VALUES (%s,%s,'second')", (f'q_{first}_{second}_2', second))
                result.append("committed")
            except DeadlockDetected:
                result.append("deadlock")

        workers = [threading.Thread(target=writer, args=("u_a", "u_b")),
                   threading.Thread(target=writer, args=("u_b", "u_a"))]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(4)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertCountEqual(result, ["committed", "committed"])
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            pending = conn.execute("SELECT count(*) FROM user_change_marker_pending").fetchone()[0]
        self.assertEqual(pending, 0)

    def test_startup_backfill_and_definition_apply_lock_order_do_not_deadlock(self):
        """실제 definition_apply는 object_defs부터 잠가 전 사용자 backfill과 교착하지 않는다."""
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("INSERT INTO object_defs(user_id,id,key,label,semantic_kind) VALUES "
                         "('u_a','od_axes','axes','Axes','collection'), ('u_b','od_axes','axes','Axes','collection')")
            conn.execute("INSERT INTO field_defs(user_id,object_id,key,label,value_type) VALUES "
                         "('u_a','od_axes','keywords','Keywords','text_list'), ('u_b','od_axes','keywords','Keywords','text_list')")
            conn.execute("CREATE FUNCTION marker_trial_pause_backfill() RETURNS trigger LANGUAGE plpgsql AS $$ "
                         "BEGIN IF current_setting('application_name')='marker_startup' THEN "
                         "PERFORM pg_advisory_xact_lock(8675309001); END IF; RETURN NEW; END $$")
            conn.execute("CREATE TRIGGER marker_trial_pause_backfill BEFORE UPDATE ON field_defs "
                         "FOR EACH ROW EXECUTE FUNCTION marker_trial_pause_backfill()")

        outcomes = []
        with psycopg.connect(DATABASE_URL, autocommit=True) as gate:
            gate.execute("SET search_path TO marker_trial")
            gate.execute("SELECT pg_advisory_lock(8675309001)")

            def startup_backfill():
                try:
                    with psycopg.connect(DATABASE_URL, application_name="marker_startup") as conn:
                        conn.execute("SET LOCAL search_path TO marker_trial")
                        conn.execute("SET LOCAL deadlock_timeout='100ms'")
                        db._backfill_template_slots(conn)
                    outcomes.append("committed")
                except DeadlockDetected:
                    outcomes.append("deadlock")

            def app_definition_write():
                try:
                    with psycopg.connect(DATABASE_URL, application_name="marker_app") as conn:
                        conn.execute("SET LOCAL search_path TO marker_trial")
                        conn.execute("SET LOCAL deadlock_timeout='100ms'")
                        # server/db.py definition_apply: object_defs FOR UPDATE 다음 field_defs 쓰기.
                        conn.execute("UPDATE object_defs SET label='Edited' WHERE user_id='u_a' AND id='od_axes'")
                        conn.execute("UPDATE field_defs SET label='Edited' WHERE user_id='u_a' AND object_id='od_axes' AND key='keywords'")
                    outcomes.append("committed")
                except DeadlockDetected:
                    outcomes.append("deadlock")

            startup = threading.Thread(target=startup_backfill)
            app_write = threading.Thread(target=app_definition_write)
            startup.start()
            app_pid = None
            for _ in range(200):
                with psycopg.connect(DATABASE_URL) as observer:
                    observer.execute("SET LOCAL search_path TO marker_trial")
                    row = observer.execute("SELECT pid FROM pg_stat_activity WHERE application_name='marker_startup' "
                                           "AND wait_event_type='Lock' LIMIT 1").fetchone()
                    if row:
                        app_pid = row[0]
                        break
                time.sleep(0.01)
            self.assertIsNotNone(app_pid, "startup backfill이 실험용 gate에서 대기하지 않았습니다")
            app_write.start()
            app_waiting = False
            for _ in range(200):
                with psycopg.connect(DATABASE_URL) as observer:
                    observer.execute("SET LOCAL search_path TO marker_trial")
                    row = observer.execute("SELECT 1 FROM pg_stat_activity WHERE application_name='marker_app' "
                                           "AND wait_event_type='Lock' LIMIT 1").fetchone()
                    if row:
                        app_waiting = True
                        break
                time.sleep(0.01)
            gate.execute("SELECT pg_advisory_unlock(8675309001)")
            startup.join(4)
            app_write.join(4)
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_trial")
            conn.execute("DROP TRIGGER marker_trial_pause_backfill ON field_defs")
            conn.execute("DROP FUNCTION marker_trial_pause_backfill()")
        self.assertTrue(app_waiting, "uid 단위 편집은 startup의 object_defs row 잠금을 기다리는 상태여야 합니다")
        self.assertFalse(startup.is_alive() or app_write.is_alive())
        self.assertCountEqual(outcomes, ["committed", "committed"])


if __name__ == "__main__":
    unittest.main()
