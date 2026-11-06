"""합성 PostgreSQL에서 실제 server/schema.sql marker migration을 검증한다. .env는 읽지 않는다."""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
import httpx
from starlette.applications import Starlette

URL = os.environ.get("DATABASE_URL", "")
parsed = urlparse(URL)
if not URL:
    raise SystemExit("DATABASE_URL을 명시하세요.")
if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != int(os.environ.get("CRM_TEST_DB_PORT", "55439")) or parsed.path != "/crm_test_user_change_marker":
    raise SystemExit(f"시험 거부: 127.0.0.1:{os.environ.get('CRM_TEST_DB_PORT', '55439')}/crm_test_user_change_marker 만 허용합니다.")

SERVER = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER))
APP_URL = URL + "?options=-csearch_path%3Dmarker_prod"
os.environ["DATABASE_URL"] = APP_URL
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "a@synthetic.test"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = "http://127.0.0.1:8800"
import db  # noqa: E402
import web  # noqa: E402

TRACKED = {
    "users", "profile", "questions", "tabs", "candidates", "candidate_history",
    "records", "record_history", "sources", "people", "source_reflections",
    "object_defs", "field_defs", "items", "item_links", "item_versions", "item_history",
    "item_stage", "confirm_events", "activities", "activity_links", "import_entries",
    "import_streams", "jobs", "stack_sessions", "std_marks", "std_choices", "optional_consents", "page_layouts",
}


class UserChangeMarkerProductionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS marker_prod CASCADE")
            conn.execute("CREATE SCHEMA marker_prod")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.row_factory = dict_row
            db.init_schema(conn)

    def setUp(self):
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("TRUNCATE users CASCADE")
            conn.execute("INSERT INTO users(id,email) VALUES ('u_a','a@synthetic.test'), ('u_b','b@synthetic.test')")

    def revision(self, uid):
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.row_factory = dict_row
            return db.user_change_revision(uid, conn)

    def test_schema_reexecution_and_trigger_coverage(self):
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.row_factory = dict_row
            db.init_schema(conn)
            rows = conn.execute("SELECT c.relname, count(*) AS n FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                                "WHERE NOT t.tgisinternal AND t.tgname LIKE 'trg_user_change_%' "
                                "AND c.relname <> 'user_change_pending' "
                                "AND c.relnamespace=current_schema()::regnamespace GROUP BY c.relname").fetchall()
        self.assertEqual({r["relname"] for r in rows}, TRACKED)
        self.assertTrue(all(r["n"] == 3 for r in rows))

    def test_bulk_write_and_all_changes_in_one_transaction_bump_once_per_user(self):
        before_a, before_b = self.revision("u_a"), self.revision("u_b")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("INSERT INTO questions(id,user_id,text) SELECT 'q_'||n::text, CASE WHEN n%2=0 THEN 'u_a' ELSE 'u_b' END, 'synthetic' "
                         "FROM generate_series(1,100) n")
            conn.execute("UPDATE questions SET text='changed' WHERE user_id='u_a'")
        self.assertEqual(self.revision("u_a"), before_a + 1)
        self.assertEqual(self.revision("u_b"), before_b + 1)
        unchanged = self.revision("u_a")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("UPDATE questions SET text=text WHERE user_id='u_a'")
        self.assertEqual(self.revision("u_a"), unchanged, "same-value UPDATE must not look like saved data changed")

    def test_rollback_cascade_and_isolation(self):
        before_a, before_b = self.revision("u_a"), self.revision("u_b")
        with self.assertRaises(RuntimeError):
            with psycopg.connect(URL) as conn:
                conn.execute("SET LOCAL search_path TO marker_prod")
                conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('rolled','u_a','x')")
                raise RuntimeError("rollback")
        self.assertEqual(self.revision("u_a"), before_a)
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('kept','u_a','x')")
        self.assertEqual(self.revision("u_a"), before_a + 1)
        self.assertEqual(self.revision("u_b"), before_b)
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("DELETE FROM users WHERE id='u_a'")
        self.assertIsNone(self.revision("u_a"))
        self.assertIsNotNone(self.revision("u_b"))

    def test_reverse_multiuser_writes_serialize_at_commit(self):
        gate = threading.Barrier(2)
        errors = []

        def writer(first, second):
            try:
                with psycopg.connect(URL) as conn:
                    conn.execute("SET LOCAL search_path TO marker_prod")
                    conn.execute("INSERT INTO questions(id,user_id,text) VALUES (%s,%s,'first')", (f'{first}{second}1', first))
                    gate.wait(2)
                    conn.execute("INSERT INTO questions(id,user_id,text) VALUES (%s,%s,'second')", (f'{first}{second}2', second))
            except BaseException as exc:
                errors.append(exc)

        before_a, before_b = self.revision("u_a"), self.revision("u_b")
        threads = [threading.Thread(target=writer, args=("u_a", "u_b")), threading.Thread(target=writer, args=("u_b", "u_a"))]
        for t in threads: t.start()
        for t in threads: t.join(4)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(self.revision("u_a"), before_a + 2)
        self.assertEqual(self.revision("u_b"), before_b + 2)

    def test_job_cancel_and_global_job_sweep_do_not_deadlock_marker(self):
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("INSERT INTO jobs(id,user_id,session_id,kind,status,expires_at) VALUES "
                         "('00000000-0000-0000-0000-000000000101','u_a','00000000-0000-0000-0000-000000000111',"
                         "'converse','queued',now()+interval '1 hour'), "
                         "('00000000-0000-0000-0000-000000000102','u_a','00000000-0000-0000-0000-000000000112',"
                         "'converse','queued',now()-interval '1 hour')")
        before = self.revision("u_a")
        sweep_ready, release_sweep = threading.Event(), threading.Event()
        outcomes = []

        def global_sweep():
            try:
                with psycopg.connect(URL, application_name="marker_job_sweep") as conn:
                    conn.execute("SET LOCAL search_path TO marker_prod")
                    conn.row_factory = dict_row
                    db._job_sweep(conn)
                    sweep_ready.set()
                    if not release_sweep.wait(3):
                        raise TimeoutError("test release not signaled")
                outcomes.append("swept")
            except BaseException as exc:
                outcomes.append(exc)

        def cancel_then_sweep():
            try:
                if not sweep_ready.wait(2):
                    raise TimeoutError("global sweep did not finish")
                with psycopg.connect(URL, application_name="marker_job_cancel") as conn:
                    conn.execute("SET LOCAL search_path TO marker_prod")
                    conn.row_factory = dict_row
                    conn.execute("UPDATE jobs SET status='cancelled', terminal_at=now() "
                                 "WHERE id='00000000-0000-0000-0000-000000000101'")
                    db._job_sweep(conn)
                outcomes.append("cancelled")
            except BaseException as exc:
                outcomes.append(exc)

        sweeper = threading.Thread(target=global_sweep)
        cancel = threading.Thread(target=cancel_then_sweep)
        sweeper.start()
        cancel.start()
        cancel_waiting = False
        for _ in range(200):
            with psycopg.connect(URL) as observer:
                row = observer.execute("SELECT 1 FROM pg_stat_activity WHERE application_name='marker_job_cancel' "
                                       "AND wait_event_type='Lock' LIMIT 1").fetchone()
                if row:
                    cancel_waiting = True
                    break
            time.sleep(0.01)
        release_sweep.set()
        sweeper.join(4)
        cancel.join(4)
        self.assertFalse(sweeper.is_alive() or cancel.is_alive())
        self.assertTrue(cancel_waiting, "cancel txn must wait for the sweeper's expired-job row")
        self.assertCountEqual(outcomes, ["swept", "cancelled"])
        self.assertEqual(self.revision("u_a"), before + 2)

    def test_parallel_schema_bootstrap_serializes_trigger_installation(self):
        barrier = threading.Barrier(2)
        errors = []

        def bootstrap():
            try:
                with psycopg.connect(URL) as conn:
                    conn.execute("SET LOCAL search_path TO marker_prod")
                    conn.row_factory = dict_row
                    barrier.wait(2)
                    db.init_schema(conn)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=bootstrap), threading.Thread(target=bootstrap)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(6)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.test_schema_reexecution_and_trigger_coverage()

    def test_startup_backfill_advances_marker_only_when_it_changes_data(self):
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("INSERT INTO object_defs(user_id,id,key,label,semantic_kind) VALUES "
                         "('u_a','od_axes','axes','Axes','collection'), ('u_b','od_axes','axes','Axes','collection')")
            conn.execute("INSERT INTO field_defs(user_id,object_id,key,label,value_type) VALUES "
                         "('u_a','od_axes','keywords','Keywords','text_list'), ('u_b','od_axes','keywords','Keywords','text_list')")
        before_a, before_b = self.revision("u_a"), self.revision("u_b")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            db._backfill_template_slots(conn)
        self.assertEqual(self.revision("u_a"), before_a + 1)
        self.assertEqual(self.revision("u_b"), before_b + 1)
        before_a, before_b = self.revision("u_a"), self.revision("u_b")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            db._backfill_template_slots(conn)
        self.assertEqual((self.revision("u_a"), self.revision("u_b")), (before_a, before_b))

    def test_upgrade_adds_markers_for_existing_users_without_losing_rows(self):
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('pre_upgrade','u_a','preserved')")
        with psycopg.connect(URL, autocommit=True) as conn:
            conn.execute("SET search_path TO marker_prod")
            conn.execute("DROP TABLE user_change_pending CASCADE")
            conn.execute("DROP TABLE user_change_markers CASCADE")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.row_factory = dict_row
            db.init_schema(conn)
        self.assertEqual(self.revision("u_a"), 0)
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            self.assertEqual(conn.execute("SELECT text FROM questions WHERE id='pre_upgrade'").fetchone()[0], "preserved")
            conn.execute("INSERT INTO questions(id,user_id,text) VALUES ('post_upgrade','u_a','tracked')")
        self.assertEqual(self.revision("u_a"), 1)

    def test_heartbeat_write_is_excluded_but_device_changes_are_tracked(self):
        before = self.revision("u_a")
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("INSERT INTO import_streams(user_id,id,channel,label) VALUES ('u_a','is_trial','board_migration','trial')")
        after_insert = self.revision("u_a")
        self.assertEqual(after_insert, before + 1)
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("UPDATE import_streams SET last_used_at=now() WHERE user_id='u_a' AND id='is_trial'")
        self.assertEqual(self.revision("u_a"), after_insert)
        with psycopg.connect(URL) as conn:
            conn.execute("SET LOCAL search_path TO marker_prod")
            conn.execute("UPDATE import_streams SET revoked_at=now() WHERE user_id='u_a' AND id='is_trial'")
        self.assertEqual(self.revision("u_a"), after_insert + 1)

    def test_authenticated_revision_endpoint_is_scoped_and_no_store(self):
        async def exercise():
            site = web.Web("https://fake.authkit.test", "http://127.0.0.1:8800", None, True, "a@synthetic.test")
            app = Starlette(routes=site.routes())
            old = site.dev, site.dev_user
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local.test") as client:
                    site.dev = False
                    self.assertEqual((await client.get("/api/state/revision")).status_code, 401)
                    site.dev, site.dev_user = True, "a@synthetic.test"
                    state = await client.get("/api/state")
                    self.assertEqual(state.status_code, 200)
                    self.assertEqual(state.headers.get("cache-control"), "no-store")
                    self.assertEqual(state.json()["revision"], self.revision("u_a"))
                    state_again = await client.get("/api/state")
                    self.assertEqual(state_again.status_code, 200)
                    self.assertEqual(state_again.json()["revision"], state.json()["revision"],
                                     "repeat clean state GET must not advance the marker")
                    response = await client.get("/api/state/revision?uid=u_b")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers.get("cache-control"), "no-store")
                    self.assertEqual(set(response.json()), {"revision"})
                    self.assertEqual(response.json()["revision"], self.revision("u_a"))
            finally:
                site.dev, site.dev_user = old
                db.close()
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
