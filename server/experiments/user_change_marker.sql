-- Scratch-only experiment. Never sourced by server/db.py or server/schema.sql.
-- Install in a private synthetic schema created from the current server/schema.sql.
CREATE TABLE IF NOT EXISTS user_change_marker (
  user_id text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
INSERT INTO user_change_marker(user_id, revision)
SELECT id, 0 FROM users ON CONFLICT (user_id) DO NOTHING;
CREATE TABLE IF NOT EXISTS user_change_marker_pending (
  txid bigint NOT NULL,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (txid, user_id)
);

CREATE OR REPLACE FUNCTION marker_trial_apply_pending() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  affected_uid text;
BEGIN
  IF EXISTS (SELECT 1 FROM user_change_marker_pending WHERE txid=NEW.txid) THEN
    -- Commit-time: no application DML remains, and all transaction uids are locked in one global order.
    FOR affected_uid IN
      SELECT user_id FROM user_change_marker_pending WHERE txid=NEW.txid ORDER BY user_id
    LOOP
      UPDATE user_change_marker SET revision=revision+1 WHERE user_id=affected_uid;
    END LOOP;
    DELETE FROM user_change_marker_pending WHERE txid=NEW.txid;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS marker_trial_apply_pending ON user_change_marker_pending;
CREATE CONSTRAINT TRIGGER marker_trial_apply_pending
AFTER INSERT ON user_change_marker_pending
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION marker_trial_apply_pending();

CREATE OR REPLACE FUNCTION marker_trial_touch_users() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  affected_uid text;
  owner_column text := TG_ARGV[0];
  affected_query text;
BEGIN
  IF TG_TABLE_NAME = 'users' AND TG_OP = 'INSERT' THEN
    INSERT INTO user_change_marker(user_id, revision)
      SELECT id, 1 FROM new_rows
      ON CONFLICT (user_id) DO NOTHING;
    RETURN NULL;
  END IF;
  IF TG_TABLE_NAME = 'users' AND TG_OP = 'DELETE' THEN
    -- The marker row is removed by its FK cascade; the deleted user cannot poll it.
    RETURN NULL;
  END IF;

  IF TG_OP = 'INSERT' THEN
    affected_query := format('SELECT DISTINCT %I::text AS uid FROM new_rows WHERE %I IS NOT NULL ORDER BY uid',
                             owner_column, owner_column);
  ELSIF TG_OP = 'DELETE' THEN
    affected_query := format('SELECT DISTINCT %I::text AS uid FROM old_rows WHERE %I IS NOT NULL ORDER BY uid',
                             owner_column, owner_column);
  ELSIF TG_TABLE_NAME = 'import_streams' THEN
    -- last_used_at is a heartbeat timestamp; its age is time-derived UI and does not advance the business marker.
    affected_query := 'SELECT DISTINCT n.user_id::text AS uid FROM new_rows n JOIN old_rows o USING (user_id,id) '
                      'WHERE (to_jsonb(n) - ''last_used_at'') IS DISTINCT FROM (to_jsonb(o) - ''last_used_at'') '
                      'ORDER BY uid';
  ELSE
    affected_query := format(
      'SELECT uid FROM (SELECT %I::text AS uid FROM old_rows UNION SELECT %I::text AS uid FROM new_rows) AS changed '
      'WHERE uid IS NOT NULL ORDER BY uid', owner_column, owner_column);
  END IF;

  -- Sorting is important when one SQL statement changes rows for several users.
  FOR affected_uid IN EXECUTE affected_query LOOP
    -- Cascaded child DELETEs after a users DELETE must not re-create pending work for a gone owner.
    IF EXISTS (SELECT 1 FROM users WHERE id=affected_uid) THEN
      INSERT INTO user_change_marker_pending(txid, user_id) VALUES (txid_current(), affected_uid)
      ON CONFLICT (txid, user_id) DO NOTHING;
    END IF;
  END LOOP;
  RETURN NULL;
END;
$$;

DO $$
DECLARE
  tbl text;
  owner_col text;
  tracked text[] := ARRAY[
    'users', 'profile', 'questions', 'tabs', 'candidates', 'candidate_history',
    'records', 'record_history', 'sources', 'people', 'source_reflections',
    'object_defs', 'field_defs', 'items', 'item_links', 'item_versions',
    'item_history', 'item_stage', 'confirm_events', 'activities', 'activity_links', 'import_entries',
    'import_streams', 'jobs', 'stack_sessions', 'std_marks', 'std_choices', 'optional_consents', 'page_layouts'
  ];
BEGIN
  FOREACH tbl IN ARRAY tracked LOOP
    IF to_regclass(tbl) IS NULL THEN
      RAISE EXCEPTION 'tracked table missing: %', tbl;
    END IF;
    owner_col := CASE WHEN tbl = 'users' THEN 'id' ELSE 'user_id' END;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = current_schema() AND table_name = tbl AND column_name = owner_col
    ) THEN
      RAISE EXCEPTION 'owner column %.% missing', tbl, owner_col;
    END IF;
    EXECUTE format('DROP TRIGGER IF EXISTS marker_trial_%I_insert ON %I', tbl, tbl);
    EXECUTE format('DROP TRIGGER IF EXISTS marker_trial_%I_update ON %I', tbl, tbl);
    EXECUTE format('DROP TRIGGER IF EXISTS marker_trial_%I_delete ON %I', tbl, tbl);
    EXECUTE format('CREATE TRIGGER marker_trial_%I_insert AFTER INSERT ON %I REFERENCING NEW TABLE AS new_rows '
                   'FOR EACH STATEMENT EXECUTE FUNCTION marker_trial_touch_users(%L)', tbl, tbl, owner_col);
    EXECUTE format('CREATE TRIGGER marker_trial_%I_update AFTER UPDATE ON %I REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows '
                   'FOR EACH STATEMENT EXECUTE FUNCTION marker_trial_touch_users(%L)', tbl, tbl, owner_col);
    EXECUTE format('CREATE TRIGGER marker_trial_%I_delete AFTER DELETE ON %I REFERENCING OLD TABLE AS old_rows '
                   'FOR EACH STATEMENT EXECUTE FUNCTION marker_trial_touch_users(%L)', tbl, tbl, owner_col);
  END LOOP;
END;
$$;
