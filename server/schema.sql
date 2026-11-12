-- My CRM — Postgres 스키마 (2026-10-18 확정, 같은 날 Codex 토론 반영). 설계 근거: data-model.md
-- 행 격리: 모든 조회·쓰기는 user_id 로 묶는다 (OWD Private). 자식은 (user_id, 부모id) 복합 FK 로 다른 사용자 행을 참조 못 한다.

CREATE TABLE IF NOT EXISTS users (
  id            text PRIMARY KEY,                 -- u_...
  email         text NOT NULL UNIQUE,             -- 소문자 정규화. 매직링크·Google 같은 이메일이면 같은 행
  auth_subject  text UNIQUE,                      -- AuthKit sub (External ID)
  created       timestamptz NOT NULL DEFAULT now(),
  -- β2(2026-10-19): 관리자 = role. 옛 DB 는 db._init_schema 가 ADD COLUMN IF NOT EXISTS 로 더한다(같은 모양).
  role               text NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
  blocked_at         timestamptz,                 -- 차단(웹·MCP 둘 다 거절). 해제 = NULL
  web_revoked_before timestamptz,                 -- 이 시각 전에 발급한 웹 세션 쿠키(iat) 무효
  mcp_revoked_before timestamptz,                 -- 이 시각 전에 발급한 MCP 토큰(iat) 무효
  desk_hidden        boolean NOT NULL DEFAULT false, -- P5: /app 문의 섹션 숨김(계정 메뉴). 옛 DB 는 db._init_schema 가 더한다
  -- PR B(2026-10-20): 「나」 = 이 행. 옛 DB 는 db._init_schema 가 같은 모양(열 → 이름 붙은 CHECK)으로 더한다.
  display_name       text,                        -- 표시 이름(필수는 쓰기 관문 NAME-REQUIRED 가 보장 — 옛 코드 INSERT 때문에 NOT NULL 아님)
  status             text NOT NULL DEFAULT 'active',   -- deleted = 삭제 CLI 실행됨(행은 남긴다). 차단(blocked_at)과 다른 말이다
  deleted_at         timestamptz,
  nav_accepted_at    timestamptz,                 -- 새 탐색 수락 시각. NULL = 기존 화면
  CONSTRAINT ck_users_display_name CHECK (display_name IS NULL OR (char_length(display_name) BETWEEN 1 AND 80 AND display_name = btrim(display_name))),
  CONSTRAINT ck_users_status CHECK (status IN ('active','deleted')),
  CONSTRAINT ck_users_deleted CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS agreements (
  id          bigserial PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('terms','privacy')),
  version     text NOT NULL,
  accepted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, kind, version)
);

CREATE TABLE IF NOT EXISTS questions (
  id       text PRIMARY KEY,                      -- q_...
  user_id  text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text     text NOT NULL,
  status   text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),  -- 삭제 없음, archive 만
  created  timestamptz NOT NULL DEFAULT now(),
  updated  timestamptz,
  UNIQUE (user_id, id)                            -- 복합 FK 대상
);

-- 출처(PR #20 §4, 2026-10-19). 사용자별. 같은 (kind, name, location) 은 한 행 — record_add 가 찾거나 만든다(SOURCES=on 일 때만).
-- 옛 records.source 문자열과 별개다(그 문자열은 보존·표시만, 자동 연결 없음 — §12). records 보다 먼저 만든다(records 의 FK 대상).
CREATE TABLE IF NOT EXISTS sources (
  user_id   text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id        text NOT NULL,                        -- s_...
  kind      text NOT NULL,
  name      text NOT NULL,
  location  text NOT NULL DEFAULT '',             -- 없으면 '' — UNIQUE 가 NULL 을 서로 다르게 보지 않게
  created   timestamptz NOT NULL DEFAULT now(),
  -- board 이전(2026-10-20): 연결 장치 활동의 일반 출처. NULL = 보통 출처. 값이 있으면 서버가 만든 일반 이름·kind other·위치 '' 뿐
  -- (게시물 제목·방 이름·메일 제목·작성자명을 넣지 않는다). 옛 DB 는 db._init_schema 가 열 → 이름 붙은 CHECK·부분 UNIQUE 를 더한다
  activity_provider text,
  PRIMARY KEY (user_id, id),
  UNIQUE (user_id, kind, name, location),
  CONSTRAINT ck_sources_kind CHECK (kind IN ('file','url','chat','other')),
  CONSTRAINT ck_sources_activity_provider CHECK (activity_provider IS NULL OR (activity_provider IN ('sns','web','mail','kakao')
                                                 AND kind = 'other' AND location = ''))
);

CREATE TABLE IF NOT EXISTS records (
  id          text PRIMARY KEY,                   -- r_...
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_id text,
  title       text NOT NULL,
  body        text NOT NULL,                      -- 수신한 그대로. 공백 하나도 안 다듬는다. 고치는 길은 수기 수정(record_edit·record_title_set)뿐 — 이력은 record_history
  source      text NOT NULL DEFAULT '대화에서 입력',
  created     timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,                        -- soft delete. 하드 삭제는 계정 삭제(users cascade) 때만
  notes       jsonb NOT NULL DEFAULT '{}',        -- 2단계: 「어디에 붙나」 중 관계가 아닌 메모 {use_at, unattached}
  -- PR①: 출처. 인용 적격 = self·verbatim·삭제 안 됨. 확인 못 한 출처는 unknown(추측 백필 금지). 본문은 불변, 출처 판정만 정정 가능
  author_kind        text  NOT NULL DEFAULT 'unknown',
  text_process       text  NOT NULL DEFAULT 'unknown',
  provenance_history jsonb NOT NULL DEFAULT '[]',  -- 생성·정정마다 {at, by, author_kind, text_process[, from, reason]}
  source_id          text,                        -- PR #20 출처 연결. NULL = 출처 미확인(옛 기록 전부). 옛 DB 는 init_schema 가 더한다
  -- board 이전(2026-10-20). 옛 DB 는 init_schema 가 열을 더한다 — 옛 행 received_at NULL·ingest_kind legacy, 새 INSERT 부터 now()·interactive.
  -- 일일 기록 한도는 COALESCE(received_at, created) 로 센다(이전한 기록의 created 가 과거여도 우회 못 한다)
  received_at        timestamptz DEFAULT now(),   -- 서버에 실제로 생긴 시각
  source_created_at  timestamptz,                 -- 확인된 원본 시각(시간대 포함)
  source_date        date,                        -- 날짜만 확인된 원본. 자정·KST 를 붙이지 않는다
  date_kind          text,                        -- 이관 경로(2026-11-02 K6): 원본 날짜 종류 written·occurred·registered·heading. NULL = 라벨 없음(이관 밖).
                                                  -- written·occurred 만 created 를 채운다 · registered·heading = source_date + 이 라벨, created = 받은 시각. 옛 DB 는 init_schema
  ingest_kind        text NOT NULL DEFAULT 'interactive',
  generation_kind    text NOT NULL DEFAULT 'unknown',
  generation_meta    jsonb NOT NULL DEFAULT '{}', -- 연결 장치가 신고한 도구·모델·입력 참조(검증된 사실 아님). 토큰·프롬프트·경로 없음
  import_batch_id    text,                        -- 처음 만든 이전 배치(FK 아님 — 대응은 import_entries)
  -- 휴지통(2026-10-23 PR-1). 업무 상태와 별개 — deleted_at·archived_at 을 쓰지 않는다. 옛 DB 는 db._migrate_trash 가 열·CHECK·인덱스를 더한다.
  -- trashed_at NULL = 일반 이용 · purge_at = 복원 기한(이동 시각 + 168h, 수동 영구 삭제 = 요청 시각) · last_trashed_at = 마지막 이동 시각(복원해도 남는다 — 그 전에 시작한 작업은 무효)
  trashed_at         timestamptz,
  purge_at           timestamptz,
  last_trashed_at    timestamptz,
  -- 수기 수정 A0′(2026-11-03). 본문·제목 수정마다 +1(이력 한 줄 = +1). 옛 DB 는 db._migrate_record_edit 가 더한다(옛 행 1)
  revision           integer NOT NULL DEFAULT 1,
  -- 세션 정리 → 판단 확정(2026-11-04 A안). 'self' = 사용자가 「내 결정」이라고 한 정리 기록 — 원문 그대로가 아니어도 인용 적격.
  -- NULL = 표시 없음(옛 행 전부 — 추측 백필 없음). 화면 어디에도 보이지 않는다(web.CORE_HIDDEN). 옛 DB 는 db._migrate_decision_owner
  decision_owner     text,
  UNIQUE (user_id, id),
  CONSTRAINT ck_records_revision CHECK (revision > 0),
  CONSTRAINT ck_records_trash CHECK ((trashed_at IS NULL) = (purge_at IS NULL) AND (trashed_at IS NULL OR last_trashed_at IS NOT NULL)),
  CONSTRAINT fk_records_source FOREIGN KEY (user_id, source_id) REFERENCES sources(user_id, id),   -- 같은 사용자 출처만
  FOREIGN KEY (user_id, question_id) REFERENCES questions(user_id, id) ON DELETE SET NULL (question_id),  -- Lookup
  CONSTRAINT ck_records_author_kind CHECK (author_kind IN ('self','external','unknown')),
  CONSTRAINT ck_records_text_process CHECK (text_process IN ('verbatim','structured','rewritten','generated','unknown')),
  CONSTRAINT ck_records_provenance_history CHECK (jsonb_typeof(provenance_history) = 'array'),
  CONSTRAINT ck_records_ingest_kind CHECK (ingest_kind IN ('legacy','interactive','inbox','board_migration')),
  -- PR ②-b: conversation = 확인 1번을 거친 대화 정리(인용 적격은 confirm_events 실재까지 — db._eligible) · routine = 루틴 결과(비적격)
  CONSTRAINT ck_records_generation_kind CHECK (generation_kind IN ('unknown','human','ai','mixed','conversation','routine')),
  CONSTRAINT ck_records_generation_meta CHECK (jsonb_typeof(generation_meta) = 'object'),
  CONSTRAINT ck_records_source_when CHECK (source_created_at IS NULL OR source_date IS NULL),
  CONSTRAINT ck_records_date_kind CHECK (date_kind IS NULL OR date_kind IN ('written','occurred','registered','heading')),
  CONSTRAINT ck_records_decision_owner CHECK (decision_owner IS NULL OR decision_owner = 'self')
);
CREATE INDEX IF NOT EXISTS ix_records_user ON records (user_id, created DESC) WHERE deleted_at IS NULL;

-- PR B 코어 「사람」(2026-10-20). 사용자 소유 별칭 이름표 하나뿐 — 다른 개인정보 열을 만들지 않는다. 기록·요약/반응과 관계 없음.
CREATE TABLE IF NOT EXISTS people (
  user_id  text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id       text NOT NULL,                         -- p_...
  alias    text CHECK (char_length(alias) BETWEEN 1 AND 80 AND alias = btrim(alias)),   -- NULL = 영구 삭제 표식(purged_at). 옛 DB 는 _migrate_trash 가 NOT NULL 을 푼다
  revision integer NOT NULL DEFAULT 0,
  created  timestamptz NOT NULL DEFAULT now(),
  updated  timestamptz NOT NULL DEFAULT now(),
  -- board 이전(2026-10-20): 연결 장치가 보낸 사람 식별자. HMAC 키·원본 계정 대응표는 PC 에만. 값이 있으면 둘 다 있다.
  -- (user_id, hmac_namespace, identity_hmac) 부분 UNIQUE 는 init_schema 가 만든다(옛 DB 에선 이 파일이 열보다 먼저 돈다)
  hmac_namespace text,
  identity_hmac  bytea,
  -- 휴지통(PR-1) — records 와 같은 뜻
  trashed_at      timestamptz,
  purge_at        timestamptz,
  last_trashed_at timestamptz,
  purged_at       timestamptz,                   -- 영구 삭제 완료 = 별칭·관계 없는 표식(HMAC 만 — 같은 사람 재생성 방지). 일반 사람으로 반환하지 않는다
  PRIMARY KEY (user_id, id),                      -- 별칭 중복 허용
  CONSTRAINT ck_people_trash CHECK ((trashed_at IS NULL) = (purge_at IS NULL) AND (trashed_at IS NULL OR last_trashed_at IS NOT NULL)),
  CONSTRAINT ck_people_purged CHECK ((alias IS NULL) = (purged_at IS NOT NULL) AND (purged_at IS NULL OR trashed_at IS NOT NULL)),
  CONSTRAINT ck_people_identity CHECK ((hmac_namespace IS NULL AND identity_hmac IS NULL)
                                       OR (hmac_namespace IS NOT NULL AND identity_hmac IS NOT NULL AND octet_length(identity_hmac) = 32))
);

-- PR B 코어 「출처 요약/반응」. 출처를 접한 뒤 내가 한 생각(자기 성찰). records 와 분리 — 인용 적격 경로(후보 근거·관계 대상)에 들어가지 않는다.
-- 검토 완료(reviewed) ≠ 판단 확정. 출처 FK 는 NO ACTION — 요약/반응이 달린 출처는 지울 수 없다.
CREATE TABLE IF NOT EXISTS source_reflections (
  user_id           text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                text NOT NULL,                -- sr_...
  source_id         text NOT NULL,
  kind              text NOT NULL CHECK (kind IN ('summary','reaction')),
  body              text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 8000),
  review            text NOT NULL DEFAULT 'pending' CHECK (review IN ('pending','reviewed')),
  revision          integer NOT NULL DEFAULT 0,
  reviewed_revision integer,
  reviewed_at       timestamptz,
  created           timestamptz NOT NULL DEFAULT now(),
  updated           timestamptz NOT NULL DEFAULT now(),
  -- 휴지통(PR-1) — records 와 같은 뜻
  trashed_at        timestamptz,
  purge_at          timestamptz,
  last_trashed_at   timestamptz,
  PRIMARY KEY (user_id, id),
  FOREIGN KEY (user_id, source_id) REFERENCES sources(user_id, id),
  CONSTRAINT ck_source_reflections_trash CHECK ((trashed_at IS NULL) = (purge_at IS NULL) AND (trashed_at IS NULL OR last_trashed_at IS NOT NULL)),
  CHECK ((review = 'reviewed') = (reviewed_at IS NOT NULL AND reviewed_revision IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_reflections_source ON source_reflections (user_id, source_id);

CREATE TABLE IF NOT EXISTS candidates (
  id             text PRIMARY KEY,                -- c_...
  user_id        text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  record_id      text NOT NULL,
  question_id    text,                            -- 2단계: NULL = 질문 없음(화면은 기록별 묶음). 복합 FK 는 NULL 이면 검사 안 함
  text           text NOT NULL,
  quote          text NOT NULL,                   -- record.body[quote_start:quote_end] 와 같다. 서버가 위치를 센다
  quote_start    integer NOT NULL,                -- 코드포인트 오프셋
  quote_end      integer NOT NULL,
  origin         text NOT NULL CHECK (origin IN ('ai','self')),
  decision       text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','confirmed','excluded')),
  edited_by_user boolean NOT NULL DEFAULT false,
  created        timestamptz NOT NULL DEFAULT now(),
  updated        timestamptz NOT NULL DEFAULT now(),
  -- PR①: 행 revision(변경마다 +1, 이력 한 줄 = +1) · 현재 문장 작성 주체(미상 NULL) · 현재 문장 승인
  revision         integer NOT NULL DEFAULT 1,
  wording_by       text,
  wording_approved boolean NOT NULL DEFAULT false,
  UNIQUE (user_id, id),
  UNIQUE (user_id, record_id, quote_start, quote_end),   -- 같은 근거 구간 재등록 방지
  FOREIGN KEY (user_id, record_id)   REFERENCES records(user_id, id)   ON DELETE CASCADE,   -- M-D: 근거 없는 판단 없음
  FOREIGN KEY (user_id, question_id) REFERENCES questions(user_id, id) ON DELETE RESTRICT,
  CONSTRAINT ck_candidates_revision CHECK (revision > 0),
  CONSTRAINT ck_candidates_wording_by CHECK (wording_by IN ('self','ai')),
  CONSTRAINT ck_candidates_wording_approval CHECK (NOT wording_approved OR wording_by IS NOT NULL),
  CONSTRAINT ck_candidates_quote_bounds CHECK (quote_start >= 0 AND quote_end > quote_start
                                               AND char_length(quote) = quote_end - quote_start)
);
CREATE INDEX IF NOT EXISTS ix_candidates_user_q ON candidates (user_id, question_id, decision);

CREATE TABLE IF NOT EXISTS candidate_history (
  id            bigserial PRIMARY KEY,
  user_id       text NOT NULL,                    -- PR①: 소유자. 복합 FK 로 다른 사용자 후보를 못 가리킨다
  candidate_id  text NOT NULL,
  action        text NOT NULL,
  prev_revision integer,                          -- 변경 전 후보 revision. 옛 이력(PR① 전)만 NULL
  prev_state    jsonb NOT NULL,                   -- 변경 전 스냅샷. v1(옛 이력) {schema_version,text,decision} ·
                                                  -- v2 {schema_version,text,decision,wording_by,wording_approved,edited_by_user,question_id}
  at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT candidate_history_action_check CHECK (action IN ('confirm','exclude','pending','edit','restore')),
  CONSTRAINT ck_candidate_history_prev_revision CHECK (prev_revision IS NULL OR prev_revision > 0),
  CONSTRAINT ck_candidate_history_prev_state CHECK (jsonb_typeof(prev_state) = 'object' AND prev_state ? 'schema_version'
                                                    AND prev_state ? 'text' AND prev_state ? 'decision'),
  CONSTRAINT uq_candidate_history_revision UNIQUE (user_id, candidate_id, prev_revision),   -- 이력 한 줄 = revision +1
  CONSTRAINT fk_candidate_history_tenant FOREIGN KEY (user_id, candidate_id)
    REFERENCES candidates(user_id, id) ON UPDATE RESTRICT ON DELETE CASCADE                  -- M-D
);
CREATE INDEX IF NOT EXISTS ix_hist_cand ON candidate_history (user_id, candidate_id, id);

CREATE TABLE IF NOT EXISTS profile (
  user_id  text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key      text NOT NULL CHECK (key IN ('purpose','refind','daily_views','first_material','separate','help_level')),
  value    jsonb NOT NULL,
  status   text NOT NULL CHECK (status IN ('confirmed','guessed','empty','off')),
  source   text NOT NULL DEFAULT '',
  updated  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS tabs (
  user_id   text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  doc       jsonb NOT NULL,                       -- 적용된 탭
  draft_doc jsonb,                                -- tabs_propose 결과. NULL 이면 제안 없음
  draft_id  text,                                 -- tabs_apply 가 이 ID 와 revision 이 맞을 때만 적용
  revision  integer NOT NULL DEFAULT 0,
  updated   timestamptz NOT NULL DEFAULT now()
);

-- 2단계 기존 테이블 변경(records.notes · candidates.question_id NULL 허용)과 PR① 코어 보수(출처·revision·이력 격리)는
-- 위 CREATE 에 반영했다(새 설치 = 최종형). 이미 있는 DB 에는 db.init_schema 가 상태를 보고 멱등 마이그레이션을 건다.

-- ── 2단계: 사용자 정의 층 (설계: data-model.md 「사용자 정의 층」) ─────────────────
-- 사용자는 오브젝트·필드·Lookup 까지만 정의한다. 증거 규칙(원문 불변·인용 1곳·후보≠판단)은 코어가 지킨다.
-- 보호 Lookup(대상 삭제 보호)은 NO ACTION — 계정 삭제 cascade 가 한 문장 안에서 끝나야 통과한다(RESTRICT 는 즉시 검사).

CREATE TABLE IF NOT EXISTS object_defs (
  user_id             text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                  text NOT NULL,                -- od_...
  key                 text NOT NULL,                -- 적용 뒤 불변
  label               text NOT NULL,                -- 화면 라벨(한글 한 단어)
  semantic_kind       text NOT NULL CHECK (semantic_kind IN ('collection','event','principle')),
  revision            integer NOT NULL DEFAULT 0 CHECK (revision >= 0),   -- 0 = 아직 적용 안 된 제안 행
  policy              jsonb NOT NULL DEFAULT '{}',  -- promotion · exactly_one_reference
  history             jsonb NOT NULL DEFAULT '[]',  -- 적용 revision 마다 전체 정의 스냅샷
  draft_doc           jsonb,
  draft_id            text,
  draft_base_revision integer,
  archived_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  template_slot       text,                         -- 템플릿 계보 `author@1:<key>`. 시드만 채운다(apply 는 안 건드림). 옛 DB 는 init_schema ADD COLUMN
  std_id              text,                         -- PR #20 표준 식별자 `std:<key>`. NULL = 표준 아님. 시드·편입만 채운다. 옛 DB 는 init_schema ADD COLUMN
  PRIMARY KEY (user_id, id),
  UNIQUE (user_id, key)
);

CREATE TABLE IF NOT EXISTS field_defs (
  user_id          text NOT NULL,
  object_id        text NOT NULL,
  key              text NOT NULL,
  label            text NOT NULL,
  value_type       text NOT NULL CHECK (value_type IN ('text','number','boolean','date','select','text_list','reference')),
  required         boolean NOT NULL DEFAULT false,
  options          jsonb NOT NULL DEFAULT '[]',     -- select: [{value,label}]
  target_kind      text CHECK (target_kind IN ('item','record','candidate','person','source','activity')),   -- 뒤 셋 = board 이전. 옛 DB 는 init_schema 가 넓힌다
  target_object_id text,
  multiple         boolean NOT NULL DEFAULT false,
  position         integer NOT NULL DEFAULT 0,
  archived_at      timestamptz,
  template_slot    text,                            -- 템플릿 계보 `author@1:<object_key>.<field_key>`. 시드만 채운다
  std_id           text,                            -- PR #20 표준 식별자 `std:<object_key>.<field_key>`. NULL = 표준 아님(사용자가 더한 필드 포함)
  PRIMARY KEY (user_id, object_id, key),
  FOREIGN KEY (user_id, object_id) REFERENCES object_defs(user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, target_object_id) REFERENCES object_defs(user_id, id),          -- 보호 Lookup
  CHECK ((value_type = 'reference') = (target_kind IS NOT NULL)),
  CHECK (target_object_id IS NULL OR target_kind = 'item')
);

CREATE TABLE IF NOT EXISTS items (
  user_id             text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                  text NOT NULL,                -- i_...
  object_id           text NOT NULL,
  schema_revision     integer NOT NULL CHECK (schema_revision > 0),
  code                text,                         -- 적용 뒤 변경·재사용 금지(서버). archive 해도 UNIQUE 유지
  title               text NOT NULL DEFAULT '',
  body                text NOT NULL DEFAULT '',
  data                jsonb NOT NULL DEFAULT '{}',  -- 일반 필드만. 관계 ID 는 item_links
  decision            text CHECK (decision IN ('pending','confirmed','excluded')),   -- principle 만 NOT NULL(서버)
  revision            integer NOT NULL DEFAULT 0 CHECK (revision >= 0),             -- 0 = 아직 적용 안 된 제안 행
  draft_doc           jsonb,
  draft_id            text,
  draft_base_revision integer,
  archived_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  -- board 이전(2026-10-20) — records 와 같은 뜻. 옛 DB 는 init_schema 가 더한다(옛 행 received_at NULL·ingest_kind legacy)
  -- ingest_kind inbox = 연결 장치 수집 글 항목(2026-11-12, collected_posts — 승인 대기 없이 바로, 일반 제안 한도에 세지 않는다)
  received_at         timestamptz DEFAULT now(),
  source_created_at   timestamptz,
  source_date         date,
  ingest_kind         text NOT NULL DEFAULT 'interactive',
  generation_kind     text NOT NULL DEFAULT 'unknown',
  generation_meta     jsonb NOT NULL DEFAULT '{}',
  import_batch_id     text,
  -- PR ②-b 판 이력: 지금 판(item_versions.id). NULL = 판 이력 없음(확인 1번으로 확정한 적 없음). FK 없음(서버 검사) — 삭제 순서가 items 보다 판이 먼저.
  -- 옛 DB 는 db._init_schema 가 더한다
  current_version_id  text,
  -- 휴지통(PR-1) — records 와 같은 뜻
  trashed_at          timestamptz,
  purge_at            timestamptz,
  last_trashed_at     timestamptz,
  PRIMARY KEY (user_id, id),
  CONSTRAINT ck_items_trash CHECK ((trashed_at IS NULL) = (purge_at IS NULL) AND (trashed_at IS NULL OR last_trashed_at IS NOT NULL)),
  UNIQUE (user_id, id, object_id),                  -- item_links 복합 FK 대상
  CONSTRAINT ck_items_ingest_kind CHECK (ingest_kind IN ('legacy','interactive','inbox','board_migration')),
  CONSTRAINT ck_items_generation_kind CHECK (generation_kind IN ('unknown','human','ai','mixed','conversation','routine')),
  CONSTRAINT ck_items_generation_meta CHECK (jsonb_typeof(generation_meta) = 'object'),
  CONSTRAINT ck_items_source_when CHECK (source_created_at IS NULL OR source_date IS NULL),
  UNIQUE (user_id, object_id, code),
  FOREIGN KEY (user_id, object_id) REFERENCES object_defs(user_id, id)                 -- 보호 Lookup
);
CREATE INDEX IF NOT EXISTS ix_items_user_obj ON items (user_id, object_id, updated_at DESC) WHERE archived_at IS NULL;

-- ── board 이전 · 연결 장치(2026-10-20, 구현계획 notes/2026-10-20_board-마이그-구현계획.md · r3 T1) ─────────────
-- 원문은 PC, 서버엔 구조화 데이터만(수집 글은 원 URL·제목 줄·AI 요약까지 — 사용자 오브젝트 collected_posts 의 항목, 원문 본문은 PC). 활동 = 코어(사용자 정의 오브젝트 아님). 계정 삭제는 db.DELETE_TABLES 순서(관계 → 접수 대응표 → 업무 자료 → 입력원).
-- 활동·접수 대응표가 참조하는 테이블보다 먼저 만든다(item_links 가 activities 를 가리킨다).

-- 입력원 = 연결 장치(토큰) 또는 board 이전(병행 기간). 장치당 현재 토큰 하나 — 옛 토큰은 감사(admin_audit)에만.
CREATE TABLE IF NOT EXISTS import_streams (
  user_id               text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                    text NOT NULL,              -- is_<hex24>
  channel               text NOT NULL CHECK (channel IN ('device','board_migration')),
  label                 text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 80 AND label = btrim(label)),
  token_id              text,                       -- it_<hex16>. 비밀값은 SHA-256 만
  secret_hash           bytea,
  token_expires_at      timestamptz,
  token_revoked_at      timestamptz,
  last_used_at          timestamptz,
  hmac_namespace        text,                       -- 키가 아닌 무작위 키 공간 ID(hn_<hex24>)
  policy                jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(policy) = 'object'),   -- 허용 행동·변환·축(로컬 경로 없음)
  policy_revision       integer NOT NULL DEFAULT 1 CHECK (policy_revision > 0),
  migration_started_at  timestamptz,
  migration_ends_at     timestamptz,
  migration_closed_at   timestamptz,
  final_manifest_sha256 bytea,
  created_at            timestamptz NOT NULL DEFAULT now(),
  revoked_at            timestamptz,                -- 장치 연결 해제(되살리지 않는다)
  -- M2 대기 토큰(PC 연결 2026-11-02) — 교체·재발급의 새 토큰. 첫 사용 때 token_* 로 올라가고 옛 토큰은 그때 무효. 1개(다음 교체가 덮어씀).
  -- UNIQUE 인덱스(ux_import_streams_pending)·CHECK(ck_import_streams_pending) 는 db._migrate_pc_connect 가 만든다(옛 DB 와 같은 길)
  pending_token_id      text,
  pending_secret_hash   bytea,
  pending_expires_at    timestamptz,
  PRIMARY KEY (user_id, id),
  UNIQUE (token_id),
  CHECK (secret_hash IS NULL OR octet_length(secret_hash) = 32),
  CHECK (final_manifest_sha256 IS NULL OR octet_length(final_manifest_sha256) = 32),
  CHECK ((channel = 'device' AND token_id IS NOT NULL AND secret_hash IS NOT NULL AND token_expires_at IS NOT NULL)
      OR (channel = 'board_migration' AND token_id IS NULL AND secret_hash IS NULL AND token_expires_at IS NULL)),
  CHECK ((migration_started_at IS NULL AND migration_ends_at IS NULL)
      OR (migration_started_at IS NOT NULL AND migration_ends_at > migration_started_at)),
  CHECK (channel = 'board_migration' OR (migration_started_at IS NULL AND migration_ends_at IS NULL
                                         AND migration_closed_at IS NULL AND final_manifest_sha256 IS NULL)),
  CHECK (migration_closed_at IS NULL OR migration_started_at IS NOT NULL)
);

-- 활동 = 불변 판. 새 개정은 새 행(옛 판을 가리키는 참조는 그대로). 집계는 import_entries.is_current_applied 가 가리키는 판만.
-- 제목·본문·메모·URL·실명 열이 없다 — 자동 경로의 핵심 방어는 자유 본문 필드 부재.
CREATE TABLE IF NOT EXISTS activities (
  user_id      text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id           text NOT NULL,                       -- a_...
  stream_id    text NOT NULL,
  source_id    text NOT NULL,                       -- 일반 출처(sources.activity_provider). 서버가 찾거나 만든다
  action       text NOT NULL CHECK (action IN ('like','repost','comment','read','save','send','reply')),
  state        text NOT NULL DEFAULT 'active' CHECK (state IN ('active','retracted')),
  occurred_on  date,                                -- 확인된 행동 날짜만(일자). 모르면 NULL — 수집일로 대체하지 않는다
  observed_on  date,                                -- 수집기가 처음 본 날(화면 「처음 수집한 날」). 기간 집계에 쓰지 않는다(구현계획 §2-11 D1)
  raw_id       text NOT NULL CHECK (raw_id ~ '^[0-9a-f]{48}$'),   -- PC 원문을 찾는 난수 ID. 실체·경로·URL 에서 유도하지 않는다
  received_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at   timestamptz,
  -- 휴지통(PR-1) — records 와 같은 뜻
  trashed_at   timestamptz,
  purge_at     timestamptz,
  last_trashed_at timestamptz,
  PRIMARY KEY (user_id, id),
  FOREIGN KEY (user_id, stream_id) REFERENCES import_streams(user_id, id),
  FOREIGN KEY (user_id, source_id) REFERENCES sources(user_id, id),
  CONSTRAINT ck_activities_trash CHECK ((trashed_at IS NULL) = (purge_at IS NULL) AND (trashed_at IS NULL OR last_trashed_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS item_links (
  user_id             text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                  bigserial,
  source_item_id      text,                         -- 출발은 item 또는 record 중 정확히 하나
  source_object_id    text,
  source_record_id    text,
  field_key           text NOT NULL,                -- item 출발: field_defs 키 · record 출발: attach_to | axes (서버 검증)
  target_item_id      text,
  target_record_id    text,
  target_candidate_id text,
  target_person_id    text,                         -- board 이전: reference 대상 person·source·activity(활동은 특정 판). 옛 DB 는 init_schema 가 더한다
  target_source_id    text,
  target_activity_id  text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, id),
  CHECK ((source_item_id IS NOT NULL AND source_object_id IS NOT NULL AND source_record_id IS NULL)
      OR (source_item_id IS NULL AND source_object_id IS NULL AND source_record_id IS NOT NULL)),
  CHECK (source_record_id IS NULL OR field_key IN ('attach_to','axes')),
  -- 대상 열 정확히 하나. 옛 DB 의 이름 없는 3열 CHECK(item_links_check2)는 init_schema 가 정의로 찾아 지우고 이 이름으로 다시 만든다
  CONSTRAINT ck_item_links_target CHECK (num_nonnulls(target_item_id, target_record_id, target_candidate_id,
                                                      target_person_id, target_source_id, target_activity_id) = 1),
  FOREIGN KEY (user_id, source_item_id, source_object_id) REFERENCES items(user_id, id, object_id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, source_object_id, field_key) REFERENCES field_defs(user_id, object_id, key),   -- 보호
  FOREIGN KEY (user_id, source_record_id) REFERENCES records(user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, target_item_id) REFERENCES items(user_id, id),                -- 보호
  FOREIGN KEY (user_id, target_record_id) REFERENCES records(user_id, id),            -- 보호
  FOREIGN KEY (user_id, target_candidate_id) REFERENCES candidates(user_id, id),      -- 보호
  CONSTRAINT fk_item_links_person FOREIGN KEY (user_id, target_person_id) REFERENCES people(user_id, id),          -- 보호
  CONSTRAINT fk_item_links_source FOREIGN KEY (user_id, target_source_id) REFERENCES sources(user_id, id),         -- 보호
  CONSTRAINT fk_item_links_activity FOREIGN KEY (user_id, target_activity_id) REFERENCES activities(user_id, id)   -- 보호
);
CREATE INDEX IF NOT EXISTS ix_links_src_item ON item_links (user_id, source_item_id);
CREATE INDEX IF NOT EXISTS ix_links_target_item ON item_links (user_id, target_item_id);
CREATE INDEX IF NOT EXISTS ix_links_target_cand ON item_links (user_id, target_candidate_id);
CREATE INDEX IF NOT EXISTS ix_links_src_record ON item_links (user_id, source_record_id);

-- 활동·기록의 사람·축·기록 연결(board 이전). 출발 = 활동 또는 기록(기록 출발은 사람만 — 기록의 축·항목은 기존 item_links(record_attach)).
CREATE TABLE IF NOT EXISTS activity_links (
  user_id           text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                text NOT NULL,                  -- al_...
  activity_id       text,
  record_id         text,
  person_id         text,
  axis_item_id      text,
  linked_record_id  text,
  relation          text NOT NULL CHECK (relation IN ('author','counterparty','participant','axis','evidence','reaction')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, id),
  FOREIGN KEY (user_id, activity_id) REFERENCES activities(user_id, id),
  FOREIGN KEY (user_id, record_id) REFERENCES records(user_id, id),
  FOREIGN KEY (user_id, person_id) REFERENCES people(user_id, id),
  FOREIGN KEY (user_id, axis_item_id) REFERENCES items(user_id, id),
  FOREIGN KEY (user_id, linked_record_id) REFERENCES records(user_id, id),
  CHECK (num_nonnulls(activity_id, record_id) = 1),
  CHECK (num_nonnulls(person_id, axis_item_id, linked_record_id) = 1),
  CHECK ((relation IN ('author','counterparty','participant') AND person_id IS NOT NULL)
      OR (relation = 'axis' AND axis_item_id IS NOT NULL)
      OR (relation IN ('evidence','reaction') AND linked_record_id IS NOT NULL)),
  CHECK (record_id IS NULL OR person_id IS NOT NULL),
  CHECK (activity_id <> '' AND record_id <> '' AND person_id <> '' AND axis_item_id <> '' AND linked_record_id <> '')   -- 빈 문자열 ID 금지(NULL 은 통과)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_activity_links_identity ON activity_links
  (user_id, COALESCE(activity_id, ''), COALESCE(record_id, ''), relation, COALESCE(person_id, ''), COALESCE(axis_item_id, ''),
   COALESCE(linked_record_id, ''));
CREATE INDEX IF NOT EXISTS ix_activity_links_person ON activity_links (user_id, person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_activity_links_axis ON activity_links (user_id, axis_item_id) WHERE axis_item_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_activity_links_linked ON activity_links (user_id, linked_record_id) WHERE linked_record_id IS NOT NULL;

-- 원본 개정 대응표 · 수신 결과 · 검토 대기 통합. 본문(payload)은 pending 에서만 — 승인·제외·만료 때 지운다. 해시·식별자·결과는 계정 존속 기간.
CREATE TABLE IF NOT EXISTS import_entries (
  user_id              text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id                   text NOT NULL,               -- ie_...
  stream_id            text NOT NULL,
  original_id          text NOT NULL,               -- PC 가 만든 불투명 ID
  source_revision      text NOT NULL,               -- 불투명 개정 ID
  previous_entry_id    text,                        -- 같은 원본·종류의 직전 접수 행. 최초 = NULL
  kind                 text NOT NULL CHECK (kind IN ('self_text','self_summary','activity',
                                                     'migration_object','migration_item','migration_record','collected_post')),   -- collected_post = 수집 글(2026-11-12). 옛 DB 는 db._WIDEN_CHECKS 가 넓힌다
  request_sha256       bytea NOT NULL CHECK (octet_length(request_sha256) = 32),
  projection_sha256    bytea NOT NULL CHECK (octet_length(projection_sha256) = 32),
  state                text NOT NULL CHECK (state IN ('pending','applied','noop','excluded','expired','deleted','reverted')),   -- deleted = 대상 영구 삭제(휴지통) 뒤 표식 — target 없음. reverted = MCP migration_revert 가 되돌린 이관 접수(최신·현재 표시 없음, 영구 삭제 뒤에도 reverted). 옛 DB 는 _migrate_trash 가 넓힌다
  is_latest_received   boolean NOT NULL DEFAULT true,
  is_current_applied   boolean NOT NULL DEFAULT false,
  payload              jsonb,
  payload_bytes        integer NOT NULL DEFAULT 0 CHECK (payload_bytes >= 0),
  expires_at           timestamptz,
  received_at          timestamptz NOT NULL DEFAULT now(),
  resolved_at          timestamptz,
  resolved_by          text CHECK (resolved_by IS NULL OR resolved_by IN ('user','expiry','superseded','system','migration')),
  target_object_id     text,
  target_item_id       text,
  target_record_id     text,
  target_activity_id   text,
  target_item_revision integer CHECK (target_item_revision >= 0),
  deleted_target_id    text,                        -- 휴지통 PR-1: state=deleted 행만 — 영구 삭제 직전 target_* 값(불투명 ID 표식, FK 없음, 본문 아님). 옛 DB 는 _migrate_trash
  batch_id             text,
  manifest_sha256      bytea,
  transform_version    text NOT NULL,
  execution            text CHECK (execution IS NULL OR execution IN ('attended','unattended')),
  -- 수집 글(2026-11-12): PC 원본 식별자(불투명 난수, 경로·URL 에서 유도하지 않음) — raw_id ↔ 항목(target_item_id) 대응. collected_post 행만.
  -- 옛 DB 는 db._migrate_collected 가 열·CHECK·부분 인덱스 ix_import_raw 를 더한다
  raw_id               text,
  PRIMARY KEY (user_id, id),
  UNIQUE (user_id, stream_id, original_id, kind, id),
  FOREIGN KEY (user_id, stream_id) REFERENCES import_streams(user_id, id),
  FOREIGN KEY (user_id, stream_id, original_id, kind, previous_entry_id)
    REFERENCES import_entries (user_id, stream_id, original_id, kind, id),
  FOREIGN KEY (user_id, target_object_id) REFERENCES object_defs(user_id, id),
  FOREIGN KEY (user_id, target_item_id) REFERENCES items(user_id, id),
  FOREIGN KEY (user_id, target_record_id) REFERENCES records(user_id, id),
  FOREIGN KEY (user_id, target_activity_id) REFERENCES activities(user_id, id),
  CHECK (manifest_sha256 IS NULL OR octet_length(manifest_sha256) = 32),
  CHECK (num_nonnulls(target_object_id, target_item_id, target_record_id, target_activity_id) <= 1),
  CHECK ((state = 'pending' AND payload IS NOT NULL AND expires_at IS NOT NULL AND resolved_at IS NULL)
      OR (state <> 'pending' AND payload IS NULL AND payload_bytes = 0 AND resolved_at IS NOT NULL)),
  CHECK (state NOT IN ('applied','noop') OR num_nonnulls(target_object_id, target_item_id, target_record_id, target_activity_id) = 1),
  CHECK (NOT is_current_applied OR state IN ('applied','noop')),
  CHECK (target_item_revision IS NULL OR target_item_id IS NOT NULL),
  CHECK (kind <> 'activity' OR state <> 'pending')
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_import_latest ON import_entries (user_id, stream_id, original_id) WHERE is_latest_received;
-- 같은 원본·같은 판은 한 행 — 되돌린 접수(reverted)는 빼서 같은 판을 다시 stage 하면 새 행으로 들어간다(가안 X §5 b).
-- 옛 DB 의 표 UNIQUE (user_id, stream_id, original_id, source_revision) 는 db._migrate_migration_path 가 정의로 찾아 이 인덱스로 바꾼다
CREATE UNIQUE INDEX IF NOT EXISTS ux_import_revision ON import_entries (user_id, stream_id, original_id, source_revision) WHERE state <> 'reverted';
CREATE UNIQUE INDEX IF NOT EXISTS ux_import_current ON import_entries (user_id, stream_id, original_id) WHERE is_current_applied;
CREATE INDEX IF NOT EXISTS ix_import_pending ON import_entries (user_id, received_at) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS ix_import_target_activity ON import_entries (user_id, target_activity_id) WHERE target_activity_id IS NOT NULL;

-- 원자적 접수·요청 한도. scope_key = 'user' 또는 장치(입력원) ID, bucket = 서버 고정 열거(imports.BUCKETS). 클라이언트 입력을 그대로 쓰지 않는다.
-- usage_daily 는 관측용이라 강제 한도에 쓰지 않는다.
CREATE TABLE IF NOT EXISTS import_counters (
  user_id       text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scope_key     text NOT NULL,
  period        text NOT NULL CHECK (period IN ('minute','day')),
  period_start  timestamptz NOT NULL,
  bucket        text NOT NULL,
  n             bigint NOT NULL DEFAULT 0 CHECK (n >= 0),
  bytes         bigint NOT NULL DEFAULT 0 CHECK (bytes >= 0),
  PRIMARY KEY (user_id, scope_key, period, period_start, bucket)
);

-- 수기 수정 A0′(2026-11-03) — 기록 본문·제목을 고친 흔적. 한 줄 = records.revision +1(prev_revision = 고치기 전 revision).
-- change: edit = {start(고치기 전 본문의 코드포인트 오프셋), old, new, deleted_candidates·moved_candidates(그때 지운·위치를 옮긴 미결 후보 수)} · title = {old, new}.
-- via = 고친 경로(web 화면 · mcp 대화). 기록이 지워지면(영구 삭제·계정 삭제) 같이 지워진다.
CREATE TABLE IF NOT EXISTS record_history (
  id            bigserial PRIMARY KEY,
  user_id       text NOT NULL,
  record_id     text NOT NULL,
  action        text NOT NULL CHECK (action IN ('edit','title')),
  prev_revision integer NOT NULL CHECK (prev_revision > 0),
  change        jsonb NOT NULL CHECK (jsonb_typeof(change) = 'object'),
  via           text NOT NULL CHECK (via IN ('web','mcp')),
  at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, record_id, prev_revision),
  FOREIGN KEY (user_id, record_id) REFERENCES records(user_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS item_history (
  id            bigserial PRIMARY KEY,
  user_id       text NOT NULL,
  item_id       text NOT NULL,
  action        text NOT NULL,                      -- apply · confirm · exclude · pending · archive · restore
  prev_revision integer NOT NULL,
  prev_state    jsonb NOT NULL,                     -- title·body·data·decision·code·schema_revision·links·archived
  event_meta    jsonb NOT NULL DEFAULT '{}',
  at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, item_id, prev_revision),         -- 이력 한 줄 = revision +1
  FOREIGN KEY (user_id, item_id) REFERENCES items(user_id, id) ON DELETE CASCADE
);

-- desk-0 문의 데스크(2026-10-19). 「본문 0」 원칙의 예외: 문의 글은 운영자가 직접 읽는다(폼·MCP 응답에 고지).
-- 종결(done·wontfix) 180일 뒤 파기(db.tickets_purge, 서버 시작 때 1회). 계정 삭제 = users cascade.
CREATE TABLE IF NOT EXISTS tickets (
  id          text PRIMARY KEY,                           -- tk_...
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('bug','request','question','privacy')),
  text        text NOT NULL CHECK (char_length(text) BETWEEN 1 AND 4096),
  via         text NOT NULL CHECK (via IN ('web','mcp')),
  page        text NOT NULL DEFAULT 'other',               -- 열거: today/question/record/structure/map/review/start/help/privacy/other
  tool        text NOT NULL DEFAULT '',                    -- MCP 도구 이름 또는 ''
  ua_family   text NOT NULL DEFAULT '',                    -- 'chrome'/'safari'/'firefox'/'edge'/'other'/'' (버전·OS 없음)
  hint        text NOT NULL DEFAULT '' CHECK (hint IN ('','privacy?')),
  status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open','ack','doing','done','wontfix')),
  admin_note  text NOT NULL DEFAULT '',
  created     timestamptz NOT NULL DEFAULT now(),
  updated     timestamptz NOT NULL DEFAULT now(),
  closed_at   timestamptz,
  reply          text CHECK (octet_length(reply) <= 4096),   -- 운영자 공개 답변(P3). NULL = 답변 없음. 옛 DB 는 init_schema ADD COLUMN
  reply_at       timestamptz,                                -- 답변을 쓰거나 고친 때
  public_updated timestamptz,                                -- 사용자에게 보이는 변경(상태·답변)의 마지막 시각. 내부 메모는 안 바꾼다
  CHECK ((status IN ('done','wontfix')) = (closed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_tickets_user ON tickets(user_id, created DESC);
CREATE INDEX IF NOT EXISTS ix_tickets_open ON tickets(status, created) WHERE status NOT IN ('done','wontfix');

-- 개인정보 요청 처리 사실. CASCADE 밖 — 계정·문의가 지워져도 남는다. 사람 식별 정보 없음. 상태 전이·파기는 desk-1(/admin).
CREATE TABLE IF NOT EXISTS privacy_log (
  id               text PRIMARY KEY,                       -- pl_...
  kind             text NOT NULL CHECK (kind IN ('access','correct_delete','stop','withdraw','other')),
  via              text NOT NULL CHECK (via IN ('form','mail')),
  ticket_id        text,                                   -- FK 없음(티켓 삭제 뒤에도 남는다)
  received         date NOT NULL,                          -- KST 날짜. 기본값 없음 — 넣는 쪽이 정한다
  notified         date,
  result           text CHECK (result IN ('done','partial','refused')),
  identity_checked boolean NOT NULL DEFAULT false,
  created          timestamptz NOT NULL DEFAULT now()
);

-- α2 사용 집계(2026-10-19). 요청 경로는 메모리 카운터만, db.usage_flush 가 5분마다 합산 upsert(수면·재배포 때 ≤5분치 유실 허용).
-- name = MCP 도구 이름 또는 web:<경로 이름>, code = OK·EXC·오류 코드(열거형만, 자유 텍스트 없음). day = KST 날짜.
-- FK 없음(익명·미동의 '' 행이 있다). 계정 삭제는 db.user_delete 가 이 테이블을 따로 지운다.
CREATE TABLE IF NOT EXISTS usage_daily (
  day      date NOT NULL,
  user_id  text NOT NULL DEFAULT '',
  name     text NOT NULL,
  code     text NOT NULL,
  n        integer NOT NULL,
  PRIMARY KEY (day, user_id, name, code)
);

-- β2 관리자 감사(2026-10-19). FK 없음 — 계정이 지워져도 남는다. detail 은 열거 키만(이메일·자유 텍스트 없음).
-- 1년(db.AUDIT_KEEP_DAYS) 지난 행은 서버 시작 때 파기(db.admin_audit_purge). bootstrap·recover 행은 파기하지 않는다 — 초기화 완료 표시라 지우면 env 를 다시 읽는다.
CREATE TABLE IF NOT EXISTS admin_audit (
  id         bigserial PRIMARY KEY,
  at         timestamptz NOT NULL DEFAULT now(),
  actor_id   text,                                -- 실행자 user id. bootstrap·recover(CLI) 는 NULL
  action     text NOT NULL CHECK (action IN ('bootstrap','recover','role_grant','role_revoke','web_signout','block','unblock',
                                         'delete_notify','delete_run','delete_cancel',
                                         'device_connect','device_reissue','device_revoke','device_policy',
                                         'migration_apply','migration_extend','migration_close','migration_token',
                                         'token_grant','token_grant_redeem','pc_forget','device_rotate')),   -- 삭제 CLI(PR B) 3종 · board 이전 7종 · 이관 토큰 1종 · PC 연결 4종(2026-11-02). 옛 DB 는 init_schema 가 넓힌다
  target_id  text,
  detail     jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_admin_audit_at ON admin_audit (at DESC);

-- 선택 동의(2026-10-19, 운영 콘솔). 처리방침 게이트(agreements) 밖 — 동의하지 않아도 모든 기능을 쓴다.
-- 현재 상태 1행(PK user_id·kind) + 이력(로그). 변경은 db.optional_consent_set 한 곳(FOR UPDATE → 상태 → 로그, 한 트랜잭션).
-- 유효 동의 = state='granted' AND version = 현재 상수(db.OPTIONAL_VERSIONS). version 은 공유 범위 문서 버전(처리방침 머리글과 별개).
CREATE TABLE IF NOT EXISTS optional_consents (
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       text NOT NULL CHECK (kind IN ('struct_names')),
  version    text NOT NULL,
  state      text NOT NULL CHECK (state IN ('granted','withdrawn')),
  changed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, kind)
);
CREATE TABLE IF NOT EXISTS optional_consent_log (
  id       bigserial PRIMARY KEY,
  user_id  text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind     text NOT NULL CHECK (kind IN ('struct_names')),
  version  text NOT NULL,
  action   text NOT NULL CHECK (action IN ('grant','withdraw')),
  at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_optional_consent_log_user ON optional_consent_log (user_id, at);

-- 1회성 마이그레이션 표식(2026-10-19). key 가 있으면 그 마이그레이션은 이미 했다 — init_schema 가 INSERT … ON CONFLICT DO NOTHING 으로 판정.
CREATE TABLE IF NOT EXISTS schema_marks (
  key  text PRIMARY KEY,
  at   timestamptz NOT NULL DEFAULT now()
);

-- 문의 이력(P3, 2026-10-19). public = 사용자에게 보이는 사건(상태·답변), internal = 운영자만(메모·재분류).
-- from_val·to_val 에는 열거값만(상태·kind). reply·note 사건은 값 없이 「바뀜」만. reason = privacy 에서 다른 kind 로 재분류한 사유.
-- 문의 파기 = cascade 로 함께 지운다.
CREATE TABLE IF NOT EXISTS ticket_history (
  id          bigserial PRIMARY KEY,
  ticket_id   text NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  at          timestamptz NOT NULL DEFAULT now(),
  actor_id    text,                                -- 실행한 관리자 user id(FK 없음 — 계정이 지워져도 남는다)
  visibility  text NOT NULL CHECK (visibility IN ('public','internal')),
  kind        text NOT NULL CHECK (kind IN ('status','reply','note','reclassify','deleted')),   -- deleted = 삭제 CLI 실행(PR B, public·값 없음)
  from_val    text CHECK (from_val IS NULL OR from_val IN ('open','ack','doing','done','wontfix','bug','request','question','privacy')),
  to_val      text CHECK (to_val IS NULL OR to_val IN ('open','ack','doing','done','wontfix','bug','request','question','privacy')),
  reason      text CHECK (reason IS NULL OR reason IN ('not_privacy','duplicate','other'))
);
CREATE INDEX IF NOT EXISTS ix_ticket_history_ticket ON ticket_history (ticket_id, at, id);

-- PR #20 표준(2026-10-19, 명세 §0·§3). std_id 를 참조하는 INDEX·CHECK 는 여기 두지 않는다 — 옛 DB 에선 이 파일이 ADD COLUMN 보다 먼저 돈다.
-- std_marks = 사용자별 설치 버전 표식. 신규 시드 시작 또는 첫 편입 때 생긴다(일부 편입이어도 있다). 없으면 std.version·state 가 null.
CREATE TABLE IF NOT EXISTS std_marks (
  user_id  text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  version  text NOT NULL,                          -- 명세 파일 주소 `std@1`. 식별자(std_id)엔 버전을 넣지 않는다
  state    text NOT NULL CHECK (state IN ('seed_pending','seeded','adopting')),
  at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, version)
);
-- std_choices = 표준 오브젝트별 사용자 상태. 행 없음 = none(아직 고르지 않음). 다시 고르면 덮어쓴다(이력 없음).
-- def_id·def_revision = 고를 때 본 같은 key 기존 오브젝트(없으면 NULL) — 적용 때 재검증용 스냅샷이라 object_defs FK 를 걸지 않는다
-- (db.user_delete 가 object_defs 를 users 보다 먼저 지운다).
CREATE TABLE IF NOT EXISTS std_choices (
  user_id            text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  std_key            text NOT NULL,                -- 표준 오브젝트 key(std@1.json)
  state              text NOT NULL CHECK (state IN ('deferred','refused','incorporated','seeded')),
  def_id             text,
  def_revision       integer CHECK (def_revision IS NULL OR def_revision >= 0),
  confirmed_meaning  boolean NOT NULL DEFAULT false,   -- 기존 오브젝트 편입 때 「같은 뜻으로 쓴다」 명시 확인(5단계)
  at                 timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, std_key),
  CONSTRAINT ck_std_choices_def CHECK ((def_id IS NULL) = (def_revision IS NULL))
);

-- 분류 역할(PR #20 §5). 사용자별 역할 하나당 오브젝트 1개. 이번 역할은 classify 뿐 — 기록 → 항목 링크(field_key='axes')의 대상 오브젝트.
-- 이관: init_schema 가 key='axes' 인 적용·미보관 오브젝트를 대상으로 잡는다(매번, 없는 사용자만 — 멱등). 신규 시드는 표준 축.
-- 오브젝트가 지워지면(계정 삭제 때 user_delete 가 object_defs 를 먼저 지운다) 같이 지운다.
CREATE TABLE IF NOT EXISTS user_roles (
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role       text NOT NULL CHECK (role IN ('classify')),
  object_id  text NOT NULL,
  at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role),
  FOREIGN KEY (user_id, object_id) REFERENCES object_defs(user_id, id) ON DELETE CASCADE
);

-- PR B 삭제 통지 메타 + contact(2026-10-20). 계정당 한 행. 실행 때 이메일·auth_subject 를 users 에서 여기로 옮긴다.
-- users FK 없음(옛 코드 user_delete 뒤에도 남게) · tickets FK 없음(파기 순서는 db.contacts_purge 가 정한다).
-- 이 행이 가리키는 문의는 180일 파기(db.tickets_purge)에서 빠지고, purge_after(= deleted_at + 1년) 뒤 이 행과 함께 파기된다.
CREATE TABLE IF NOT EXISTS deletion_contacts (
  user_id      text PRIMARY KEY,
  ticket_id    text NOT NULL,                     -- 삭제 요청 문의(kind='privacy')
  requested_at timestamptz NOT NULL,              -- = 그 문의 created
  notified_at  timestamptz NOT NULL,              -- 공개 통지 시각
  delete_after timestamptz NOT NULL,              -- = notified_at + 7일
  email        text,
  auth_subject text,
  deleted_at   timestamptz,
  purge_after  timestamptz,
  CHECK ((deleted_at IS NULL) = (purge_after IS NULL)),
  CHECK (deleted_at IS NOT NULL OR (email IS NULL AND auth_subject IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_deletion_contacts_email ON deletion_contacts (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_deletion_contacts_subject ON deletion_contacts (auth_subject) WHERE auth_subject IS NOT NULL;

-- PR ①-b 페이지 레이아웃(2026-10-22, 구현계획 §3). 사용자당 한 행 — 「나」 하위 탭 순서·요약 블록 순서. 기본값은 코드(db.DEFAULT_LAYOUT) 한 곳.
-- 행 없음 = 기본 + version 0. layout NULL = [기본으로 되돌리기] 뒤(기본 + 그 version) — 행을 지우지 않아 버전이 되감기지 않는다(옛 탭의 PUT 이 STALE).
-- 관리자 API 없음. 계정 삭제는 db.DELETE_TABLES.
CREATE TABLE IF NOT EXISTS page_layouts (
  user_id    text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  layout     jsonb CHECK (layout IS NULL OR jsonb_typeof(layout) = 'object'),
  version    integer NOT NULL CHECK (version > 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- PR ②-a 작업 전달(2026-10-22, 구현계획 §5). 세션(session_id) = 여러 실행을 묶는 불투명 ID, 작업 = PC 실행 1번.
-- 이 행엔 본문이 없다 — 입력·결과(미확정 내용 전체)는 임시 보관(tmp 스키마, db._init_tmp 가 만든다 — 운영 백업 -n public 밖, 24h 만료 삭제).
-- 종료 표식 = status·terminal_at·reason_code(코드만). CLI 세션 ID 는 PC 에만. 계정 삭제는 db.DELETE_TABLES(입력원 앞) + tmp 명시 삭제.
CREATE TABLE IF NOT EXISTS jobs (
  id                  uuid PRIMARY KEY,
  user_id             text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id          uuid NOT NULL,
  kind                text NOT NULL CHECK (kind IN ('converse','summarize_reading','routine_ingest')),
  status              text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','leased','running','result_ready','confirmed','failed',
                                                                      'cancelled','expired','needs_check')),
  device_id           text,                       -- 임대한 장치(import_streams.id). 임대 전 NULL. FK 없음 — 옛 DB 재현 시험이 import_streams 를 지운다
  lease_generation    integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at    timestamptz,
  input_version       integer NOT NULL DEFAULT 1 CHECK (input_version > 0),
  definitions_version text,                       -- ②-b 구조 정의 스냅샷 sha256 hex(최초 발급 때 고정). ②-a 는 NULL. 옛 DB integer → init_schema 가 text 로
  edit_generation     integer NOT NULL DEFAULT 0 CHECK (edit_generation >= 0),   -- ②-b 이 작업을 접수할 때의 세션 편집 세대. 옛 DB 는 init_schema
  parent_result_version uuid,                     -- ②-b 재정리 작업이면 원 결과 버전. 옛 DB 는 init_schema
  attempts            integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),   -- 입력 조회 성공 수(PC 시도 기록)
  reason_code         text CHECK (reason_code IN ('output-not-json','output-shape','result-shape','timeout','cli-exit','login',
                                                  'input-too-large')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  expires_at          timestamptz NOT NULL,       -- created_at + 24h(서버 시각). 연장 없음
  terminal_at         timestamptz,
  UNIQUE (user_id, id),
  CHECK ((status IN ('confirmed','failed','cancelled','expired','needs_check')) = (terminal_at IS NOT NULL)),
  CHECK (status <> 'failed' OR reason_code IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_jobs_queue ON jobs (user_id, created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS ix_jobs_session ON jobs (user_id, session_id);

-- PR ②-b 쌓기 단계·확인 1번(2026-10-22, 구현계획 §3-1). 이 표들엔 본문이 없다 — 입력·결과·미리보기(정리 글·변경 목록)는 임시 보관
-- (tmp 스키마, db._init_tmp). 계정 삭제는 db.DELETE_TABLES + user_delete(items cascade).
-- 세션 = 대화 하나(여러 작업). 만료 = 최초 입력 + 24h 고정(후속 턴·재정리로 연장 없음). 확정은 세션당 1번(confirm_events UNIQUE).
CREATE TABLE IF NOT EXISTS stack_sessions (
  id                uuid PRIMARY KEY,                 -- = jobs.session_id(FK 없음, 서버 검사)
  user_id           text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  input_kind        text NOT NULL CHECK (input_kind IN ('converse','verbatim')),   -- 첫 입력 때 정한다. 재정리로 바뀌지 않는다
  latest_job_id     uuid,                             -- 이 세션에서 가장 늦게 접수한 작업
  latest_preview_id uuid,                             -- 그 작업의 최신 미리보기(tmp). 없으면 NULL
  edit_generation   integer NOT NULL DEFAULT 0 CHECK (edit_generation >= 0),
  expires_at        timestamptz NOT NULL,
  confirm_event_id  uuid,                             -- 확정되면 그 확인 이벤트
  created_at        timestamptz NOT NULL DEFAULT now(),
  terminal_at       timestamptz,                      -- 확정·만료 시각
  UNIQUE (user_id, id),
  CHECK (confirm_event_id IS NULL OR terminal_at IS NOT NULL)
);

-- 확인 이벤트 = 사용자가 미리보기 하나(버전·해시)를 보고 [확정] 1번. 대화 정리 기록의 인용 적격 근거(db._eligible). 계정 존속 기간 보관.
-- request_id = 화면이 만든 확정 요청 ID(멱등 키). response = 성공 응답의 식별자만(본문 없음) — 같은 요청 재전송에 그대로 돌려준다.
CREATE TABLE IF NOT EXISTS confirm_events (
  id               uuid PRIMARY KEY,
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id       uuid NOT NULL,
  job_id           uuid NOT NULL,
  preview_id       uuid NOT NULL,
  preview_version  integer NOT NULL CHECK (preview_version > 0),
  preview_sha      text NOT NULL CHECK (preview_sha ~ '^[0-9a-f]{64}$'),
  request_id       text NOT NULL CHECK (request_id ~ '^[A-Za-z0-9_-]{8,64}$'),
  final_text_sha   text NOT NULL CHECK (final_text_sha ~ '^[0-9a-f]{64}$'),
  response         jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(response) = 'object'),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, id),
  UNIQUE (user_id, request_id),
  UNIQUE (user_id, session_id)                      -- 세션당 확정 1번
);

-- 판 이력 = 확인 1번으로 확정한 판단(principle) 항목의 불변 판. 확정 판은 고치지 않는다 — 새 판 + 이전 판 ID. 인용은 당시 판을 가리킨다.
CREATE TABLE IF NOT EXISTS item_versions (
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id               text NOT NULL,                    -- iv_...
  item_id          text NOT NULL,
  version_no       integer NOT NULL CHECK (version_no > 0),
  prev_version_id  text,
  item_revision    integer NOT NULL CHECK (item_revision > 0),   -- 이 판을 만든 뒤의 items.revision
  fields           jsonb NOT NULL CHECK (jsonb_typeof(fields) = 'object'),   -- {title, body, data, decision, code}
  links            jsonb NOT NULL CHECK (jsonb_typeof(links) = 'array'),
  confirm_event_id uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, id),
  UNIQUE (user_id, item_id, version_no),
  FOREIGN KEY (user_id, item_id) REFERENCES items(user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, prev_version_id) REFERENCES item_versions(user_id, id),
  FOREIGN KEY (user_id, confirm_event_id) REFERENCES confirm_events(user_id, id),
  CHECK ((version_no = 1) = (prev_version_id IS NULL))
);

-- stage = 서버가 계산하는 관리값(직접 수정 API 없음). 판단의 확정 기준은 items.decision. 규칙 = stack_service.compute_stage(rule_version).
-- item_revision = 계산에 쓴 items.revision — 다르면(또는 규칙 버전이 다르면) 읽을 때 다시 계산한다(lazy, 백필 없음).
CREATE TABLE IF NOT EXISTS item_stage (
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id          text NOT NULL,
  stage            text NOT NULL CHECK (stage IN ('draft','organized','confirmed')),
  rule_version     integer NOT NULL CHECK (rule_version > 0),
  item_revision    integer NOT NULL CHECK (item_revision >= 0),
  item_version_id  text,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, item_id),
  FOREIGN KEY (user_id, item_id) REFERENCES items(user_id, id) ON DELETE CASCADE
);

-- 이관 경로(2026-11-02, notes/2026-11-02_이관경로-구현계획.md K1·가안 1). 옛 DB 도 이 CREATE … IF NOT EXISTS 가 만든다(새 표뿐).
-- 이관 토큰 = 이관 전용 scope 장치 토큰(일반 연결 장치 토큰 import_streams 와 분리). 웹 로그인 세션에서만 발급, 14일 만료, 비밀값은 SHA-256 만.
-- 토큰 원문 = "mig_<id>.<secret>" — 발급 응답에서 한 번만 보인다. 사용자당 살아 있는 토큰 1개(새로 발급하면 앞 토큰 폐기).
CREATE TABLE IF NOT EXISTS migration_tokens (
  user_id      text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id           text NOT NULL,                     -- mt_<hex16>
  secret_hash  bytea NOT NULL CHECK (octet_length(secret_hash) = 32),
  label        text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 80 AND label = btrim(label)),
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  last_used_at timestamptz,
  PRIMARY KEY (user_id, id),
  UNIQUE (id),
  CHECK (expires_at > created_at)
);

-- 이관 plan(상태기계 staged → sealed → applied → reverted · → cancelled · → expired). 서버가 토큰으로 사용자를 정한다(본문에 사용자 필드 없음).
-- plan_hash = SHA-256(JCS(seq 순 item_sha256 hex 목록)) — seal 때 고정. 반영은 웹 세션 또는 MCP(가안 X, CRM_MIGRATION_MCP_ENABLED), 저장한 바이트만 쓴다.
-- via = 반영 경로(web·mcp, 반영 때 기록 — 옛 행 NULL). reverted = MCP migration_revert(이 plan 이 새로 만든 대상만 휴지통, applied_at 은 남는다).
-- 만료(만든 시각 + 3일)·취소·반영 뒤 항목 본문(migration_plan_items.payload)은 바로 영구 삭제(휴지통 아님). 해시·영수증만 남는다.
CREATE TABLE IF NOT EXISTS migration_plans (
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id               text NOT NULL,                 -- mp_<hex24>
  token_id         text,                          -- 만든 이관 토큰(FK 없음 — 토큰을 지워도 plan 영수증은 남는다)
  contract         text NOT NULL CHECK (contract = 'board-migration/2'),
  source_instance  text NOT NULL,                 -- PC 인스턴스 표식(불투명). 항목의 source_instance 와 같아야 한다
  state            text NOT NULL CHECK (state IN ('staged','sealed','applied','cancelled','expired','reverted')),
  item_count       integer NOT NULL DEFAULT 0 CHECK (item_count BETWEEN 0 AND 200),
  staged_bytes     integer NOT NULL DEFAULT 0 CHECK (staged_bytes >= 0),
  plan_hash        bytea CHECK (plan_hash IS NULL OR octet_length(plan_hash) = 32),
  summary          jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(summary) = 'object'),   -- seal 집계·반영 영수증 집계(개수만, 본문 없음)
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  sealed_at        timestamptz,
  applied_at       timestamptz,
  closed_at        timestamptz,                   -- cancelled·expired 시각
  reverted_at      timestamptz,                   -- reverted 시각(가안 X). 옛 DB 는 db._migrate_migration_path 가 더한다
  via              text,                          -- 반영 경로 web·mcp(가안 X 감사). 반영 전·옛 행 NULL
  PRIMARY KEY (user_id, id),
  CHECK (state NOT IN ('sealed','applied') OR (plan_hash IS NOT NULL AND sealed_at IS NOT NULL)),
  CONSTRAINT ck_migration_plans_applied CHECK ((state IN ('applied','reverted')) = (applied_at IS NOT NULL)),   -- 옛 이름 없는 CHECK 는 init_schema 가 바꾼다
  CONSTRAINT ck_migration_plans_reverted CHECK ((state = 'reverted') = (reverted_at IS NOT NULL)),
  CONSTRAINT ck_migration_plans_via CHECK (via IS NULL OR via IN ('web','mcp')),
  CHECK ((state IN ('cancelled','expired')) = (closed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_migration_plans_open ON migration_plans (expires_at) WHERE state IN ('staged','sealed');

-- plan 항목 = 받은 순(seq). payload = 받은 항목 JSON 그대로(본문 포함) — 반영은 이 값만 쓴다. 본문 없는 열(해시·action·결과·대상 id)이 영수증이다.
-- target_id 는 FK 없음(import_batch_id 선례) — 영구 삭제된 대상도 영수증은 남는다. 반영 배치 ID(import_batch_id) = plan id.
CREATE TABLE IF NOT EXISTS migration_plan_items (
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan_id          text NOT NULL,
  seq              integer NOT NULL CHECK (seq >= 0),
  original_id      text NOT NULL,
  source_revision  text NOT NULL,
  unit_kind        text NOT NULL,
  target_kind      text NOT NULL CHECK (target_kind IN ('record','item','source')),
  content_hash     bytea NOT NULL CHECK (octet_length(content_hash) = 32),
  item_sha256      bytea NOT NULL CHECK (octet_length(item_sha256) = 32),   -- JCS(항목)의 SHA-256 — plan_hash 의 원소
  payload          jsonb,
  payload_bytes    integer NOT NULL DEFAULT 0 CHECK (payload_bytes >= 0),
  action           text CHECK (action IS NULL OR action IN ('insert','noop','conflict','reject','warn')),
  reason           text,                          -- reject·conflict·warn 사유 코드(값 없음)
  checked          boolean NOT NULL DEFAULT false,   -- 기준(principle_c·principle_wd) 항목 확인 체크 — 웹 세션만
  result           text CHECK (result IS NULL OR result IN ('applied','noop','skipped_unchecked','skipped_warn','skipped_reject',
                                                            'skipped_conflict')),
  target_id        text,
  applied_at       timestamptz,
  created          boolean,                       -- 가안 X: 반영이 대상을 새로 만들었나(true = 되돌리기 때 휴지통, false = 기존 대상 갱신·noop). 옛 행 NULL(모름)
  decision_deferred boolean NOT NULL DEFAULT false,   -- 가안 X: MCP 반영이 decision=confirmed 기준을 pending 으로 낮춰 넣었다
  PRIMARY KEY (user_id, plan_id, seq),
  UNIQUE (user_id, plan_id, original_id),
  FOREIGN KEY (user_id, plan_id) REFERENCES migration_plans(user_id, id) ON DELETE CASCADE,
  CHECK (payload IS NOT NULL OR payload_bytes = 0),
  CHECK ((result IS NULL) = (applied_at IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_migration_items_hash ON migration_plan_items (user_id, content_hash);
CREATE INDEX IF NOT EXISTS ix_migration_items_applied ON migration_plan_items (user_id, applied_at) WHERE result = 'applied';

-- 앱 로그인 넘김(2026-11-02) — 시스템 브라우저 로그인(/auth/callback) 뒤 앱(mycrm://auth/callback)으로 넘기는 일회용 코드.
-- 코드 원문은 저장하지 않는다(SHA-256 만). challenge = base64url(sha256(verifier)) — verifier 는 앱 메모리에만. state 는 앱이 만든 값 그대로.
-- 2분 만료 · 일회용(used_at) · 만료 행은 발급 때마다 지운다. 사용자 삭제 = cascade(+ DELETE_TABLES).
CREATE TABLE IF NOT EXISTS desktop_handoffs (
  code_hash   bytea PRIMARY KEY CHECK (octet_length(code_hash) = 32),
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  challenge   text NOT NULL CHECK (challenge ~ '^[A-Za-z0-9_-]{43}$'),
  state       text NOT NULL CHECK (state ~ '^[A-Za-z0-9_-]{16,64}$'),
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  loopback    boolean NOT NULL DEFAULT false,   -- PC 연결(2026-11-02) — CLI --browser(RFC 8252 loopback) 코드. /desktop/cli/claim 만 받는다(앱 코드와 섞지 않는다)
  CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS ix_desktop_handoffs_exp ON desktop_handoffs (expires_at);
CREATE INDEX IF NOT EXISTS ix_desktop_handoffs_user ON desktop_handoffs (user_id);

-- PC 연결·토큰 대화 발급(2026-11-02 가안 2 「상주 앱 수령형」, notes/2026-11-02_pc-connect-구현계획.md §4). 옛 DB 도 이 CREATE … IF NOT EXISTS 가 만든다.
-- 설치본 = 로그인한 데스크톱 앱 하나(앱이 userData 에 id 보관). IP·호스트 이름·경로는 저장하지 않는다 — 이름·OS·시각만.
-- device_id = 이 PC 의 연결 장치(import_streams.id, FK 없음 — 계정 삭제 순서로 지운다). revoked_at = 대화(pc_forget)로 해제한 기록 —
-- 자동 연결·교체가 해제된 PC 를 되살리지 않게 지킨다(대화 pc_connect 수령 때만 풀린다). last_seen_at = 마지막 폴링(지목 규칙 「최근 2분」).
CREATE TABLE IF NOT EXISTS desktop_installations (
  user_id       text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id            text NOT NULL CHECK (id ~ '^di_[0-9a-f]{24}$'),
  client_name   text NOT NULL CHECK (char_length(client_name) BETWEEN 1 AND 80 AND client_name = btrim(client_name)),
  os            text NOT NULL CHECK (os IN ('darwin','win32','linux')),
  device_id     text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at    timestamptz,
  PRIMARY KEY (user_id, id),
  UNIQUE (id)
);
CREATE INDEX IF NOT EXISTS ix_desktop_installations_seen ON desktop_installations (user_id, last_seen_at DESC);

-- 토큰 grant = 대화가 「이 PC 로 토큰을 보내라」고 남긴 대기 표. 토큰 값·해시는 없다 — 토큰은 앱이 redeem 하는 그 요청 안에서 발급된다.
-- scope device(장치 토큰) · migration(이관 토큰). waiting → delivered(redeem) | expired(10분) | cancelled(pc_forget). via = 만든 경로.
-- delivered_to = 받은 장치·설치본 이름(감사·상태 표시용). 만료 정리 = imports.expire_pending 회차(30일 지난 행 삭제).
CREATE TABLE IF NOT EXISTS token_grants (
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  id               text NOT NULL CHECK (id ~ '^tg_[0-9a-f]{24}$'),
  scope            text NOT NULL CHECK (scope IN ('device','migration')),
  installation_id  text NOT NULL,
  state            text NOT NULL DEFAULT 'waiting' CHECK (state IN ('waiting','delivered','expired','cancelled')),
  via              text NOT NULL CHECK (via IN ('mcp')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  delivered_at     timestamptz,
  delivered_to     text CHECK (delivered_to IS NULL OR char_length(delivered_to) BETWEEN 1 AND 80),
  PRIMARY KEY (user_id, id),
  UNIQUE (id),
  FOREIGN KEY (user_id, installation_id) REFERENCES desktop_installations(user_id, id) ON DELETE CASCADE,
  CHECK (expires_at > created_at),
  CHECK ((state = 'delivered') = (delivered_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_token_grants_inst ON token_grants (user_id, installation_id, state);
CREATE INDEX IF NOT EXISTS ix_token_grants_created ON token_grants (user_id, created_at);

-- 웹 「대화」(2026-11-04 PR 1, notes 구현계획 §2) — 내 PC 의 구독 CLI 가 답하고 서버는 중계·보관만 한다(모델 호출 없음).
-- 세션 = 사용자·장치 하나(사용자당 active 1). 턴 = 사용자 입력 하나(세션당 running 1). 이벤트 = PC 가 낸 출력 조각(턴 안 seq 1부터).
-- 메시지 = 사용자 입력·턴 끝에 합친 답. 보관 = created_at + 30일(webchat.purge — main.purge_once 회차, 활동으로 연장 없음).
-- 계정 삭제 = chat_sessions(db.DELETE_TABLES) → 자식 표는 cascade. device_id 는 import_streams.id — FK 없음(jobs.device_id 와 같은 이유).
CREATE TABLE IF NOT EXISTS chat_sessions (
  id               text PRIMARY KEY CHECK (id ~ '^cs_[0-9a-f]{24}$'),
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id        text NOT NULL,
  provider         text CHECK (provider IS NULL OR char_length(provider) BETWEEN 1 AND 40),   -- 첫 턴을 보낼 때 PC hello 의 providers[0]
  model            text,
  client_session_id text,
  binding_version  smallint NOT NULL DEFAULT 0,
  cli_session_ref  text CHECK (cli_session_ref IS NULL OR char_length(cli_session_ref) BETWEEN 1 AND 200),   -- PC 가 보낸 CLI 세션 ID(재개용)
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_sessions_active ON chat_sessions (user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_chat_sessions_user ON chat_sessions (user_id, created_at);

CREATE TABLE IF NOT EXISTS chat_turns (
  id               text PRIMARY KEY CHECK (id ~ '^ct_[0-9a-f]{24}$'),
  session_id       text NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  client_turn_id   text NOT NULL CHECK (char_length(client_turn_id) BETWEEN 1 AND 64),
  status           text NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed','stopped')),
  n_events         integer NOT NULL DEFAULT 0 CHECK (n_events >= 0),   -- 저장한 이벤트 수(턴 한도·재생 상한 — 매번 세지 않는다)
  n_bytes          bigint NOT NULL DEFAULT 0 CHECK (n_bytes >= 0),     -- 이벤트 data 의 압축 JSON UTF-8 바이트 합(webchat._jbytes 기준)
  created_at       timestamptz NOT NULL DEFAULT now(),
  ended_at         timestamptz,
  UNIQUE (session_id, client_turn_id),
  CHECK ((status = 'running') = (ended_at IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_turns_running ON chat_turns (session_id) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS ix_chat_turns_session ON chat_turns (session_id, created_at, id);
CREATE INDEX IF NOT EXISTS ix_chat_turns_created ON chat_turns (created_at);

-- A model can propose a guarded action, but only the signed-in user can
-- confirm the server-owned preview. Rows are deleted with their chat session.
CREATE TABLE IF NOT EXISTS chat_approvals (
  id               text PRIMARY KEY CHECK (id ~ '^ca_[0-9a-f]{24}$'),
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id       text NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  turn_id          text NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
  op               text NOT NULL,
  params           jsonb NOT NULL CHECK (jsonb_typeof(params) = 'object'),
  preview          jsonb NOT NULL CHECK (jsonb_typeof(preview) = 'object'),
  result           jsonb CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
  state            text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','confirmed','cancelled')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  finished_at      timestamptz,
  CHECK ((state = 'pending') = (finished_at IS NULL))
);
ALTER TABLE chat_approvals ADD COLUMN IF NOT EXISTS result jsonb CHECK (result IS NULL OR jsonb_typeof(result) = 'object');
-- 대화 하나로 F(2026-11-11): write 등급 카드. 기존 행은 decide 로 읽는다. preview = {op, shown, impact, irreversible, hash}(write) 또는 facade preview(decide)
ALTER TABLE chat_approvals ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'decide' CHECK (kind IN ('decide','write'));
CREATE INDEX IF NOT EXISTS ix_chat_approvals_session ON chat_approvals (user_id, session_id, created_at);

CREATE TABLE IF NOT EXISTS chat_events (
  turn_id          text NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
  seq              integer NOT NULL CHECK (seq > 0),
  kind             text NOT NULL CHECK (kind IN ('delta','tool_call','tool_result','done','error')),
  data             jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (turn_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_chat_events_created ON chat_events (created_at);

CREATE TABLE IF NOT EXISTS chat_messages (
  id               text PRIMARY KEY CHECK (id ~ '^cm_[0-9a-f]{24}$'),
  session_id       text NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  turn_id          text NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
  role             text NOT NULL CHECK (role IN ('user','assistant')),
  body             text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (turn_id, role)
);
CREATE INDEX IF NOT EXISTS ix_chat_messages_session ON chat_messages (session_id, created_at);
CREATE INDEX IF NOT EXISTS ix_chat_messages_created ON chat_messages (created_at);

-- PC 명시 승인 grant(2026-11-06, D7 기반) — 실제 공급자 세션을 열기 전 PC 가 한 번 허용했다는 기록.
CREATE TABLE IF NOT EXISTS chat_provider_grants (
  id           text PRIMARY KEY CHECK (id ~ '^cg_[0-9a-f]{24}$'),
  user_id      text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id    text NOT NULL CHECK (char_length(device_id) BETWEEN 1 AND 200),
  provider     text NOT NULL CHECK (provider IN ('claude','codex')),
  model        text CHECK (model IS NULL OR char_length(model) BETWEEN 1 AND 120),
  request_id   text NOT NULL CHECK (request_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  state        text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','approved','consumed')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  approved_at  timestamptz,
  consumed_at  timestamptz,
  UNIQUE (user_id, request_id),
  CHECK (expires_at > created_at),
  CHECK ((state = 'pending') = (approved_at IS NULL)),
  CHECK ((state = 'consumed') = (consumed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_chat_provider_grants_created ON chat_provider_grants (created_at);
-- 대화 하나로 F9(2026-11-11): PC 동의 창이 허용 없이 끝난 이유(PC 앱이 consent.result 로 알린다). 권한을 줄이기만 한다.
-- 값이 있으면 그 grant 는 challenge 발급, 서명 검증, 소비가 모두 거절된다. pending grant 에만 쓴다. state CHECK 는 그대로
ALTER TABLE chat_provider_grants ADD COLUMN IF NOT EXISTS close_reason text CHECK (close_reason IN ('declined','locked','failed'));

CREATE TABLE IF NOT EXISTS desktop_consent_keys (
  id               text PRIMARY KEY CHECK (id ~ '^ck_[0-9a-f]{24}$'),
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  installation_id  text NOT NULL,
  device_id        text NOT NULL CHECK (char_length(device_id) BETWEEN 1 AND 200),
  spki             bytea NOT NULL CHECK (octet_length(spki) = 44),
  state            text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','active','revoked')),
  pop_nonce        text NOT NULL UNIQUE CHECK (pop_nonce ~ '^[A-Za-z0-9_-]{22,128}$'),
  pop_expires_at   bigint NOT NULL CHECK (pop_expires_at > 0),
  created_at       timestamptz NOT NULL DEFAULT now(),
  activated_at     timestamptz,
  revoked_at       timestamptz,
  FOREIGN KEY (user_id, installation_id) REFERENCES desktop_installations(user_id, id) ON DELETE CASCADE,
  CHECK ((state = 'pending') = (activated_at IS NULL AND revoked_at IS NULL) OR state = 'revoked'),
  CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_desktop_consent_keys_active ON desktop_consent_keys (user_id, installation_id) WHERE state = 'active';

CREATE TABLE IF NOT EXISTS chat_consent_challenges (
  id               text PRIMARY KEY CHECK (id ~ '^cc_[0-9a-f]{24}$'),
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id        text NOT NULL CHECK (char_length(device_id) BETWEEN 1 AND 200),
  installation_id  text NOT NULL,
  key_id           text NOT NULL REFERENCES desktop_consent_keys(id) ON DELETE CASCADE,
  grant_id         text NOT NULL REFERENCES chat_provider_grants(id) ON DELETE CASCADE,
  session_id       text NOT NULL CHECK (session_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  provider         text NOT NULL CHECK (provider IN ('claude','codex')),
  model            text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 120),
  nonce            text NOT NULL UNIQUE CHECK (nonce ~ '^[A-Za-z0-9_-]{22,128}$'),
  expires_at       bigint NOT NULL CHECK (expires_at > 0),
  state            text NOT NULL DEFAULT 'issued' CHECK (state IN ('issued','verified','rejected','expired','revoked')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  settled_at       timestamptz,
  FOREIGN KEY (user_id, installation_id) REFERENCES desktop_installations(user_id, id) ON DELETE CASCADE,
  CHECK ((state = 'issued') = (settled_at IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_chat_consent_challenges_grant ON chat_consent_challenges (user_id, grant_id, state);

-- 대화 하나로 J(2026-11-12, JD1~JD3): 서 있는 허용 — (사용자, 장치, 공급자)마다 한 번. 첫 세션이 서명 검증된 grant 를 소비할 때 만든다.
-- 그 뒤 같은 공급자의 새 대화와 다른 모델 대화는 PC 에 다시 묻지 않는다. 살아 있음 = key_id 키 active + 설치본 해제 안 됨 + 장치 토큰 유효.
-- 키 회전(activate 가 옛 키를 갈 때)은 key_id 를 새 키로 옮긴다. 기록은 해제(웹, PC 앱), 장치 해제, 웹 토큰 재발급, keys/revoke 때 지운다.
-- 30일 정리 대상이 아니다(쓰는 동안 남는다). grant_id, challenge_id 는 성립 근거의 식별자일 뿐 FK 가 없다 — 그 행들은 30일 정리로 사라진다.
-- key_id, installation_id 도 FK 가 없다(없는 키 = 판정 실패). 계정 삭제 = db.DELETE_TABLES.
CREATE TABLE IF NOT EXISTS chat_provider_permits (
  id               text PRIMARY KEY CHECK (id ~ '^cp_[0-9a-f]{24}$'),
  user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id        text NOT NULL CHECK (char_length(device_id) BETWEEN 1 AND 200),
  provider         text NOT NULL CHECK (provider IN ('claude','codex')),
  installation_id  text NOT NULL CHECK (installation_id ~ '^di_[0-9a-f]{24}$'),
  key_id           text NOT NULL CHECK (key_id ~ '^ck_[0-9a-f]{24}$'),
  grant_id         text NOT NULL CHECK (grant_id ~ '^cg_[0-9a-f]{24}$'),
  challenge_id     text NOT NULL CHECK (challenge_id ~ '^cc_[0-9a-f]{24}$'),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, device_id, provider)
);
CREATE INDEX IF NOT EXISTS ix_chat_provider_permits_inst ON chat_provider_permits (user_id, installation_id);
CREATE INDEX IF NOT EXISTS ix_chat_provider_permits_key ON chat_provider_permits (key_id);
-- 세션이 묶인 허용. NULL(J 이전 세션) = 재확인에서 닫힌 실패
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS permit_id text;

-- 사용자별 저장 데이터 변경 revision — 주기 polling의 가벼운 확인용.
-- 고정 대상 표: /api/state 및 그 UI 보조 GET이 읽는 지속 자료. last_used_at은 heartbeat라 전용 예외로 뺀다.
-- generated·recent/offline 임계값·lease 만료처럼 시계 경과만으로 바뀌는 표시는 DB 변경이 없으므로 revision 대상이 아니다.
CREATE TABLE IF NOT EXISTS user_change_markers (
  user_id   text PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  revision  bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
INSERT INTO user_change_markers(user_id, revision)
SELECT id, 0 FROM users ON CONFLICT (user_id) DO NOTHING;

-- 문장별 영향 uid를 트랜잭션당 한 행으로 모은다. commit-time trigger가 uid 정렬 순으로 marker를 잠가
-- 여러 문장·다중 사용자 작업의 중간 marker 잠금 역전을 피한다.
CREATE TABLE IF NOT EXISTS user_change_pending (
  txid    bigint NOT NULL,
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (txid, user_id)
);

CREATE OR REPLACE FUNCTION crm_apply_user_change_pending() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  affected_uid text;
BEGIN
  IF EXISTS (SELECT 1 FROM user_change_pending WHERE txid=NEW.txid) THEN
    FOR affected_uid IN
      SELECT user_id FROM user_change_pending WHERE txid=NEW.txid ORDER BY user_id
    LOOP
      UPDATE user_change_markers SET revision=revision+1 WHERE user_id=affected_uid;
    END LOOP;
    DELETE FROM user_change_pending WHERE txid=NEW.txid;
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION crm_track_user_change_statement() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  affected_uid text;
  owner_column text := TG_ARGV[0];
  affected_query text;
BEGIN
  IF TG_TABLE_NAME='users' AND TG_OP='INSERT' THEN
    INSERT INTO user_change_markers(user_id, revision)
      SELECT id, 0 FROM new_rows ON CONFLICT (user_id) DO NOTHING;
    RETURN NULL;
  END IF;
  -- 계정 삭제는 인증 불가가 된다. marker와 pending은 FK cascade로 같이 없어지고, 조회할 주체도 없다.
  IF TG_TABLE_NAME='users' AND TG_OP='DELETE' THEN
    RETURN NULL;
  END IF;

  IF TG_OP='INSERT' THEN
    affected_query := format('SELECT DISTINCT %I::text AS uid FROM new_rows WHERE %I IS NOT NULL ORDER BY uid', owner_column, owner_column);
  ELSIF TG_OP='DELETE' THEN
    affected_query := format('SELECT DISTINCT %I::text AS uid FROM old_rows WHERE %I IS NOT NULL ORDER BY uid', owner_column, owner_column);
  ELSIF TG_TABLE_NAME='import_streams' THEN
    -- last_used_at은 폴 heartbeat. 그 값만 바뀐 UPDATE는 marker에 넣지 않는다.
    affected_query := 'SELECT DISTINCT row_data->>''user_id'' AS uid FROM ('
      '((SELECT to_jsonb(n) - ''last_used_at'' AS row_data FROM new_rows n) EXCEPT '
      '(SELECT to_jsonb(o) - ''last_used_at'' AS row_data FROM old_rows o)) '
      'UNION ALL '
      '((SELECT to_jsonb(o) - ''last_used_at'' AS row_data FROM old_rows o) EXCEPT '
      '(SELECT to_jsonb(n) - ''last_used_at'' AS row_data FROM new_rows n))'
      ') changed WHERE row_data->>''user_id'' IS NOT NULL ORDER BY uid';
  ELSE
    affected_query := format(
      'SELECT DISTINCT row_data->>%L AS uid FROM ('
      '((SELECT to_jsonb(n) AS row_data FROM new_rows n) EXCEPT (SELECT to_jsonb(o) AS row_data FROM old_rows o)) '
      'UNION ALL '
      '((SELECT to_jsonb(o) AS row_data FROM old_rows o) EXCEPT (SELECT to_jsonb(n) AS row_data FROM new_rows n))'
      ') changed WHERE row_data->>%L IS NOT NULL ORDER BY uid', owner_column, owner_column);
  END IF;

  FOR affected_uid IN EXECUTE affected_query LOOP
    -- Cascaded child DELETE after users DELETE must not recreate pending rows for a missing owner.
    IF EXISTS (SELECT 1 FROM users WHERE id=affected_uid) THEN
      INSERT INTO user_change_pending(txid, user_id) VALUES (txid_current(), affected_uid)
      ON CONFLICT (txid, user_id) DO NOTHING;
    END IF;
  END LOOP;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_user_change_pending_commit ON user_change_pending;
CREATE CONSTRAINT TRIGGER trg_user_change_pending_commit
AFTER INSERT ON user_change_pending DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION crm_apply_user_change_pending();

DO $$
DECLARE
  tbl text;
  ev text;
  owner_col text;
  trig text;
  tracked text[] := ARRAY[
    'users','profile','questions','tabs','candidates','candidate_history','records','record_history',
    'sources','people','source_reflections','object_defs','field_defs','items','item_links','item_versions',
    'item_history','item_stage','confirm_events','activities','activity_links','import_entries','import_streams',
    'jobs','stack_sessions','std_marks','std_choices','optional_consents','page_layouts'
  ];
BEGIN
  FOREACH tbl IN ARRAY tracked LOOP
    owner_col := CASE WHEN tbl='users' THEN 'id' ELSE 'user_id' END;
    IF to_regclass(tbl) IS NULL OR NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema=current_schema() AND table_name=tbl AND column_name=owner_col
    ) THEN
      RAISE EXCEPTION 'user change marker target or owner column missing: %.%', tbl, owner_col;
    END IF;
    FOREACH ev IN ARRAY ARRAY['INSERT','UPDATE','DELETE'] LOOP
      trig := 'trg_user_change_' || tbl || '_' || lower(ev);
      IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(tbl) AND tgname=trig AND NOT tgisinternal) THEN
        IF ev='INSERT' THEN
          EXECUTE format('CREATE TRIGGER %I AFTER INSERT ON %I REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT '
                         'EXECUTE FUNCTION crm_track_user_change_statement(%L)', trig, tbl, owner_col);
        ELSIF ev='DELETE' THEN
          EXECUTE format('CREATE TRIGGER %I AFTER DELETE ON %I REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT '
                         'EXECUTE FUNCTION crm_track_user_change_statement(%L)', trig, tbl, owner_col);
        ELSE
          EXECUTE format('CREATE TRIGGER %I AFTER UPDATE ON %I REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT '
                         'EXECUTE FUNCTION crm_track_user_change_statement(%L)', trig, tbl, owner_col);
        END IF;
      END IF;
    END LOOP;
  END LOOP;
END;
$$;
