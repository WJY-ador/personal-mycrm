# 데이터 모델 (2026-10-18 확정 · 2026-11-02 이관 경로·이관 MCP(가안 X)·PC 연결(가안 2) · 2026-11-03 수기 수정 A0′·레이아웃 v2까지 정정)

전제: 사용자 AI 클라이언트 → MCP → 이 서버 → Postgres. 서버 모델 호출 0. 사용자 10~100명, 1인당 월 기록 10~30편 — 작아서 파티션·아카이브 없음. DDL은 `schema.sql`. `db.py` 는 psycopg(Postgres) 판이다(끝 절).

## 용어 대응 (Salesforce → Postgres)
| Salesforce | 여기 |
|---|---|
| Object · key prefix | 테이블 · ID 접두 `u_ q_ r_ c_` |
| Lookup | nullable FK, `ON DELETE SET NULL` |
| Master-Detail | `NOT NULL` FK, `ON DELETE CASCADE`, 소유자 부모 상속 |
| Picklist | `CHECK` |
| Field History | `candidate_history` |
| OWD Private | 모든 행 `user_id`, 모든 쿼리 `user_id` 필터 |
| External ID | `users.auth_subject` |

## 오브젝트 목록
| 오브젝트 | 용도 | 관계 |
|---|---|---|
| users | 계정. 이메일 하나 = 사용자 하나 | — |
| agreements | 옛 약관·개인정보 동의 이력(2026-10-19 필수 동의 제거 뒤 새로 쓰지 않음) | users M-D |
| questions | 계속 돌아오는 질문. 삭제 없음, `archived` 만 | users M-D |
| records | 기록 원문. soft delete · `revision`(수기 수정마다 +1) | users M-D · questions Lookup |
| record_history | 기록 본문·제목 수정 이력(2026-11-03 수기 수정 A0′) — 아래 「수기 수정」 절 | records M-D |
| candidates | 판단 후보. 두 축 `origin`(ai/self) × `decision`(pending/confirmed/excluded) | users M-D(반정규화) · records M-D · questions RESTRICT |
| candidate_history | 결정 이력, 되돌리기 근거. `user_id`·`prev_revision`·`prev_state`(변경 전 스냅샷) | candidates M-D(`(user_id,candidate_id)` 복합 FK) |
| profile | 프로필 항목 key-value, 상태 4값 | users M-D |
| tabs | 화면 탭. `doc`=적용본, `draft_doc`=제안 | users M-D |
| (2단계) object_defs·field_defs·items·item_links·item_history | 사용자 정의 층 — 아래 절 | users M-D |
| (board 이전·연결 장치) import_streams·import_entries·import_counters·activities·activity_links·people·source_reflections | 연결 장치 입력원·접수 대응표·한도 카운터·활동·사람·출처 요약/반응 — DDL 주석이 정본(`schema.sql`) | users M-D |
| (쌓기·휴지통·화면) jobs·stack_sessions·confirm_events·item_versions·item_stage·page_layouts | 작업 전달·쌓기 세션·확인 이벤트·항목 판·단계·레이아웃 — DDL 주석이 정본. 레이아웃 모양은 아래 「레이아웃 계약 v2」 | users M-D |
| (이관 경로, 2026-11-02) migration_tokens·migration_plans·migration_plan_items | 이관 토큰·이관 plan·plan 항목(영수증) — 아래 「이관 경로」 절 | users M-D |
| (앱 로그인 넘김, 2026-11-02) desktop_handoffs | 시스템 브라우저 로그인(`/desktop/login` → `/auth/callback`) 뒤 앱(`mycrm://auth/callback`)이 `/desktop/claim` 으로 세션을 받는 일회용 코드. 코드 원문은 저장하지 않는다(`code_hash` = SHA-256) · `challenge` = base64url(sha256(verifier)), verifier 는 앱 메모리에만 · 앱 `state` 그대로 · 2분 만료 · `used_at` 일회용(교환은 UPDATE 한 문장) · 만료 행은 발급 때마다 지운다. 로그·감사에 값 없음 · `loopback`(PC 연결 2026-11-02) = CLI `--browser` 코드(`redirect_uri=http://127.0.0.1|[::1]:<port>/cb` 로 302, `/desktop/cli/claim` 만 받는다 — 앱 코드와 섞지 않는다) | users M-D |
| (PC 연결, 2026-11-02 가안 2) desktop_installations·token_grants | 로그인한 데스크톱 앱 설치본(이름·OS·로그인·폴링 시각·해제 기록·연결 장치 id — IP 없음)과 대화가 남긴 토큰 전달 요청(scope device·migration, 10분, 토큰 값·해시 없음) — 아래 「PC 연결」 절 | users M-D |
| tickets | 문의(desk-0). 종류 bug/request/question/privacy · via web/mcp/auto(auto = 오류 자동 Case, 2026-11-13: `auto_key`(출처, 단계, 코드) `auto_day`(KST) 묶음 UNIQUE, `auto_count` `auto_first` `auto_last` `auto_meta`(코드와 고정 낱말만), 사용자 하루 20건, 사람이 쓴 문의 한도와 따로, 스위치 `auto_cases`) · page·tool·브라우저 계열 · `hint`(오분류 개인정보 요청 표식) · 상태 open/ack/doing/done/wontfix(종결 ⇔ `closed_at`) · `admin_note`(사용자 응답에 없음). 사용자 하루 10건·전역 100건(KST), 종결 180일 뒤 파기 | users M-D |
| privacy_log | 개인정보 요청 처리 사실(받은 날·종류·통지한 날·결과·본인 확인). 사람 식별 정보 없음. kind=privacy 문의와 같은 트랜잭션에서 1행 | 없음 — CASCADE 밖, `ticket_id` FK 없음(문의가 지워져도 남는다) |

## 판단 로그
- **「본문 0」 원칙의 예외: 문의 글.** 운영자가 사용자 글을 읽는 곳은 `tickets.text` 하나다. 폼·MCP 응답에 「운영자가 직접 읽어요」 고지, 「내 문의」는 본인 글·상태·공개 답변·공개 이력만(운영자 메모·hint·내부 이력 없음), 관리자(`users.role=admin`)만 `/admin/tickets/<id>` 레코드 페이지에서 글·이메일·메모를 보고 상태·답변·메모·종류를 바꾼다(사건은 `ticket_history`, 리스트·리포트엔 글 없음), 전역 DB 크기 거절(QUOTA-GLOBAL)은 면제하고 하루 한도로 막는다.
- 질문은 삭제 금지. 확정 판단 밑 질문이 사라지면 판단 근거가 끊긴다 — `candidates.question_id` RESTRICT + `archived`.
- 기록→질문은 Lookup. 질문을 archive 해도 기록은 남는다.
- 기록 삭제는 soft delete(`deleted_at`). 후보는 기록 M-D — 기록 하드 삭제(계정 삭제) 때만 같이 사라진다. 근거 없는 판단을 남기는 안(Lookup SET NULL)은 제품 원칙 위반이라 버렸다.
- `candidates.user_id` 반정규화 유지. 행 격리 필터·인덱스에 join 없음. 자식은 `(user_id, 부모id)` 복합 FK — DB 가 다른 사용자의 기록·질문 참조를 막는다(Codex 토론: 앱 필터만으론 교차 참조를 못 막음).
- 근거 구간은 문자열이 아니라 **위치**(`quote_start`,`quote_end`)로 식별한다. 모델은 문자열만 보내고 서버가 원문에서 위치를 센다. 원문에 같은 구간이 2곳 이상이면 저장하지 않고 "앞뒤를 포함해 더 길게" 돌려준다. `UNIQUE (user_id, record_id, quote_start, quote_end)` — 같은 구간 재등록 방지. 같은 문장이 두 질문에 답하면 사용자가 질문 하나를 고른다(의도 확인 2026-10-18). Codex 토론: 문자열 키는 반복 문장을 하나로 합친다.
- 후보 결정 컬럼은 `decision`. 테이블마다 뜻 다른 `status` 를 없앤다. MCP 도구 인자명은 그대로 — ChatGPT 가 승인 시점 스키마를 고정하므로.
- 탭 제안→적용은 같은 행 `draft_doc`+`draft_id` 로. 적용은 제안 ID 와 기반 revision 이 맞을 때만. 동시에 제안 하나만 — 사용자 1명이 미리보기 하나 보는 흐름이라 충분. 별도 테이블은 안 만든다.
- `agreements` 는 옛 이력만(2026-10-19 필수 동의 제거 — 처리 근거는 처리방침 공개, `server/README.md` 「처리방침」 절). 로컬 판의 읽기 경로 동의(`read_paths`)는 호스팅에서 뜻이 없어 버린다.
- `profile` 은 key-value 유지. 항목 추가에 마이그레이션 없음.
- `candidate_history` 에 `user_id` 있음(PR①, 2026-10-18 정정 — 전엔 부모 상속이었다). `(user_id, candidate_id) → candidates(user_id, id)` 복합 FK(ON UPDATE RESTRICT, ON DELETE CASCADE)로 다른 사용자 후보에 이력을 못 단다. 조회도 `user_id` 로 거른다. 근거: raw R5.

## 출처·revision (PR① 코어 보수, 2026-10-18)
imports(3단계)가 기대는 저장 계약을 코어에 먼저 넣었다. 기능은 같고 저장 계약만 바뀐다. 근거: 레포 `notes/raw/2026-10-18_schema-round2-astra.md` §4·R3~R5, 구현계획 `notes/2026-10-18_PR1-코어보수-구현계획.md`.

| 대상 | 컬럼 | 뜻 |
|---|---|---|
| records | `author_kind` self/external/unknown · `text_process` verbatim/structured/rewritten/generated/unknown · `provenance_history` jsonb 배열 · `decision_owner` NULL/self(2026-11-04) | 누가 쓴 글이고 얼마나 손댔나. 생성·정정마다 한 줄 · self = 사용자가 「이 정리의 결정은 내가 했다」고 한 정리 기록(화면 어디에도 안 보인다 — `web.CORE_HIDDEN`) |
| candidates | `revision`(1부터, 변경마다 +1) · `wording_by` self/ai/NULL · `wording_approved` | 행 버전 · 현재 문장 작성 주체(미상 NULL) · 현재 문장 승인 |
| candidate_history | `user_id` · `prev_revision` · `prev_state` jsonb | 변경 전 스냅샷. v1 = PR① 전 이력(text·decision 만, prev_revision NULL) · v2 = text·decision·wording_by·wording_approved·edited_by_user·question_id |

### 판단 로그
- **인용 적격** = `db._ELIGIBLE_SQL` 한 곳: `author_kind='self' AND deleted_at IS NULL AND trashed_at IS NULL AND ((text_process='verbatim' AND generation_kind NOT IN ('ai','routine')) OR decision_owner='self' OR (generation_kind='conversation' AND 확인 이벤트 실재))`(PR ②-b·휴지통 PR-1 뒤 — 2026-11-02 정정 · 세션 정리 A안 2026-11-04). 곧 근거는 **원문 그대로이거나, 내가 결정했다고 표시한 정리 기록**이다. 확정 재검사(`contract.review_reason`)도 같은 뜻 — `decision_owner='self'` 면 processed 가 아니다. 후보(판단 근거)는 적격 기록에서만 만든다 — 비적격이면 dropped 「이 기록은 본인 원문이 아니라 근거로 쓸 수 없어요」. 승격 근거 수도 적격 기록의 확정 후보만 센다. 목록에서는 빼지 않는다.
- 기존 기록은 `unknown` 그대로 둔다. 과거 기록 전부를 self/verbatim 으로 백필할 근거가 없다. MCP `record_add` 는 사용자가 대화에서 직접 준 말이라 self/verbatim(사용자가 「내 결정」이라고 말하면 `decision_owner=self` 인자). `decision_owner=self` 는 author_kind=self 에만(아니면 ARG-INVALID). `author_kind='external'` 입력은 `SCOPE-SELF-ONLY`(PR #20 — 서버는 작성자 표시만 검사, 내용은 확인 못 함). 확정(confirm·edit_confirm)도 근거 기록을 다시 검사해 비적격이면 `CANDIDATE-REVIEW`(사유 author_unknown·external·processed·deleted), 미확정 후보 응답에 `review`. 이미 확정한 판단은 그대로.
- 인용 구간은 생성 뒤 불변. 본문은 수기 수정(아래 「수기 수정」 절)으로만 바뀌고, 내가 결정한 판단이 붙은 글은 고칠 수 없다. **작성 판정은 정정 가능**(`record_provenance_set`, 사유 필수 · `decision_owner` 인자 「비움 = 그대로 · self · none」). 후보가 있는 기록의 적격 → 비적격 정정은 거절(`PROVENANCE-LOCKED`, 바꾼 뒤 적격인지로 본다) — 과거 오판정은 별도 복구 작업. 작성자·가공 방식은 그대로 두고 `decision_owner` 만 바꾸는 정정은 생성 잠금(`PROVENANCE-AI-LOCKED`)을 받지 않는다 — 세션 정리 기록(mixed)도 표시를 고칠 수 있다. 후보 생성과 출처 정정은 같은 기록 행을 `FOR UPDATE` 로 잠가 경합을 막는다. 직접 SQL 은 이 계약을 우회할 수 있다(트리거는 지인 시험 뒤, raw R3).
- 후보 변경 = 변경 전 스냅샷 이력 한 줄 + revision+1(`UNIQUE(user_id,candidate_id,prev_revision)`). 같은 결정 반복은 no-op(revision 그대로). 웹 결정은 `expected_revision`(선택)이 틀리면 CONFLICT. MCP 도구는 revision 인자를 받지 않는다(서명 불변).
- 문장 수정(edit·edit_confirm)은 `wording_approved=false`·pending. `wording_by` 는 웹 편집 self, MCP edit 은 모름(NULL). 새 후보는 origin=ai 면 ai, self 면 NULL(AI 가 다듬었는지 모름). 승인(`wording_approved=true`) 경로는 아직 없다 — 다음 PR.
- 복원(`candidate_restore`)도 새 변경: 지금 상태를 이력(action=restore)으로 남기고 revision+1. v1 이력은 text·decision 만, wording_by NULL. 승인은 넘기지 않는다(승인은 그 revision 에 대한 것). 웹·MCP 노출은 다음 PR.
- 이력 응답의 옛 키 `prev_text`·`prev_status` 는 `prev_state` 에서 꺼내 호환한다.
- 마이그레이션은 `db.init_schema` 가 서버 시작 때 상태를 보고 한 번만(한 트랜잭션·LOCK·실패 시 전체 롤백). `prev_decision`·`prev_text` 를 지우므로 **옛 코드와 같이 돌 수 없다**.

## 사용자 정의 층 (2단계, 2026-10-18)
공통 코어(원문·인용·확정·이력·격리) + 제한된 정의 층. 사용자는 오브젝트·필드·Lookup 까지만 정의한다. 수식·롤업·자동화·사용자 M-D 없음.
증거 규칙(결정이 붙은 원문은 잠김·인용 1곳·후보≠판단)은 코어가 지키고 정의로 바꿀 수 없다. 근거: 레포 `notes/2026-10-18_내-구조-서버-스키마-매핑.md`.

| 오브젝트 | 용도 | 관계 |
|---|---|---|
| object_defs | 오브젝트 정의. `semantic_kind` collection/event/principle · `policy`(승격·대상 규칙) · `history`(적용 revision 마다 전체 정의 스냅샷) · draft_* · `template_slot`(템플릿 계보, 시드만) | users M-D |
| field_defs | 필드. `value_type` text/number/boolean/date/select/text_list/reference · select `options`=[{value,label}] · reference 는 target_kind(item/record/candidate/person/source/activity — 뒤 셋은 board 이전)·target_object_id·multiple. 빠진 필드는 `archived_at` · `template_slot`(시드만) | object_defs M-D · 대상 오브젝트 보호 Lookup |
| items | 항목. `code`(적용 뒤 변경·재사용 금지) · title · body · `data`(일반 필드만) · `decision`(principle 만) · revision · draft_* | object_defs 보호 Lookup |
| item_links | 관계. 출발은 item(필드 key) 또는 record(`attach_to`·`axes`) 중 하나 → 대상 item/record/candidate/person/source/activity 중 정확히 하나(`ck_item_links_target`). 값은 data 가 아니라 여기. record 출발 `axes` 의 대상 오브젝트는 `user_roles`(classify)가 정한다(PR #20) | 출발 M-D · 대상 보호 Lookup |
| item_history | 항목 이력. `prev_state`(title·body·data·decision·code·schema_revision·links·archived) + `prev_revision` | items M-D |

기존 테이블 변경: `records.notes jsonb`(「어디에 붙나」 중 쓸 자리·아직 안 붙는 것) · `candidates.question_id` NULL 허용(질문 없는 후보 — 화면은 기록별 묶음). `init_schema` 가 상태를 보고 멱등 ALTER.

### 판단 로그
- 제안과 적용을 나눈다. MCP 는 `*_propose` 로 draft 만 쓰고, 적용(`definition_apply`·`item_decide apply`)과 기준 확정은 사용자가 말했을 때만. 웹은 결정만(항목 본문 편집 없음).
- 새 정의·새 항목 제안은 `revision=0` 행으로 둔다. 일반 조회에서 빠지고, 적용하면 1. 행당 제안 하나 — 새 제안이 덮고, 낡은 제안 ID 적용은 CONFLICT.
- 모든 변경은 행 잠금 + `expected_revision`. 틀리면 CONFLICT. 항목 이력 한 줄 = revision +1(`UNIQUE(user_id,item_id,prev_revision)`). 되돌리기(restore)도 새 변경이다.
- 결정 축은 principle 에만. 일반 항목은 apply·archive·restore 만. 제안 버리기는 `discard` + `proposal_id`(새 항목 제안이면 행 삭제, 아니면 draft 만 비움, 이력·revision 변화 없음). `exclude` 는 기준의 「남기지 않기」 전용.
- 정의 적용은 기존 항목을 깨면 거절한다 — 필수 추가·타입 변경·옵션 축소·multiple 해제·대상 변경·항목 있는 오브젝트의 종류 변경. key 는 적용 뒤 불변.
- 관계 검증은 서버: reference 필드만, 대상 종류·같은 사용자·살아 있는 대상·대상 오브젝트·단일성. 다른 사용자 대상은 복합 FK 전에 LINK-INVALID 로 거절.
- 계정 삭제는 정의 층 자식부터 지운다(`user_delete`). 보호 Lookup(NO ACTION) 때문에 users cascade 만으로는 `field_defs.target_object_id` FK 에 막힌다(2026-10-18 실측).

### 승격 정책
principle 정의의 `policy.promotion`. 기본 `{"confirmed_claims_min":2,"claim_field":"evidence_claims","distinct_events_min":0}` — 신규 기준 정의엔 `evidence_claims`(후보, 다중) 필드를 서버가 넣는다.
센다: 연결된 후보 중 확정이고 기록이 지워지지 않은 것. 결정(event) 조건(`distinct_events_min`·`event_field`·`event_claim_field`)은 연결된 결정 항목 중 그 판단이 이 기준의 확정 근거에도 있는 것.
`confirm` 은 미충족이어도 거절하지 않는다. 결과에 `promotion: {met, …}` 사실만 싣고 판단은 사용자 몫.

### 원작자 템플릿 (`template_author.py`)
정의 데이터일 뿐 테이블이 아니다. 기준 `od_principles`(principle, register·maturity·근거 판단·근거 결정·관심 축, 결정 2개 조건) · 결정 `od_events`(event) · 숙제 `od_open_questions`(대상 기준·결정·판단 중 정확히 하나) · 발행 `od_publications` · 축 `od_axes` · 접근 방식 `od_craft`. 라벨은 정의 데이터라 뒤에 바꿀 수 있다 — 시드 라벨은 `template_author.py` 맨 위 `LABELS`(동결 뒤엔 판을 올린다 — 아래 계보), 화면 코어 라벨(질문·기록·후보 등)은 `app.html` 의 `const LABELS` 한 곳. questions 자동 생성 없음, works·E 카드 제외.

**템플릿 계보 (`template_slot`, 2026-10-19).** 템플릿 여부는 id 가 아니라 이 열로 판정한다 — 사용자도 `od_axes` 같은 id 를 직접 만들 수 있어서다. 정의 구분(core·standard·template·custom)은 `std_id` 우선 → `template_slot` → custom(`contract.origin_of`, PR #20).
- 형식: 오브젝트 `author@1:<object_key>` · 필드 `author@1:<object_key>.<field_key>`. 판(`@1`)이 문자열에 들어 있다.
- 시드만 채운다: `template_author.seed` 가 `definition_apply` 직후 `db.template_slot_mark` 를 한 번 부른다. MCP·웹 경로는 이 함수를 부르지 않고, 정의 JSON 에 `template_slot` 을 넣어도 정규화가 버린다. `definition_apply` 의 `ON CONFLICT … DO UPDATE SET`·`UPDATE` 에 이 열이 없다 → 사용자가 고쳐 적용해도(필드 빼기·다시 넣기 포함) 슬롯이 남는다. 사용자가 더한 필드는 NULL.
- 동결: `TEMPLATE_KEY="author"`·`TEMPLATE_VERSION=1` + `server/templates/author@1.json`(정규화 정의 덤프). `TEMPLATE`·`LABELS` 를 바꾸면 시험이 깨진다 — 판을 올리고 새 판 파일을 만든다(옛 판 파일은 남긴다).
- 백필: `init_schema` 4단계(멱등, `template_slot IS NULL` 만). 동결 v1 의 id·key **쌍**이 둘 다 같은 오브젝트, 그 아래 key 가 템플릿 필드 key 인 필드. key 는 비교만 한다. 한계: 사용자가 시드 전에 id·key 를 둘 다 템플릿과 똑같이 만들었으면 템플릿으로 잡힌다(드묾, 수용). 시드가 적용 뒤 표시 전에 끊겨도 다음 시작 때 백필이 채운다.

## 표준·출처·역할 (PR #20, 2026-10-19)
| 대상 | 내용 | 관계 |
|---|---|---|
| object_defs·field_defs `std_id` | 표준 식별자 `std:<key>[.<field>]`(버전 무관). NULL = 표준 아님. 시드·편입만 채운다. 있으면 잠금(`STANDARD-LOCKED`) | — |
| std_marks | 사용자·표준 판(`std@1`)마다 1행. state seed_pending(신규 시드 실패 대기)·seeded·adopting(기존 사용자 첫 편입) | users M-D |
| std_choices | 사용자·표준 오브젝트마다 1행. state deferred·refused·incorporated·seeded, 고를 때 본 def_id·def_revision, confirmed_meaning. 행 없음 = none. 덮어쓰기(이력 없음) | users M-D |
| sources | 기록 출처(사용자별). kind file·url·chat·other · name · location · UNIQUE(user, kind, name, location) · `activity_provider`(board 이전 — 활동 일반 출처, 그때는 kind other·location '') · 이관 출처는 location = 로컬 anchor 해시(URL 아님) | users M-D |
| records `source_id` | 출처 연결(nullable, 복합 FK 로 같은 사용자 출처만). 옛 기록은 NULL(「출처 미확인」), 옛 `source` 문자열 보존 | sources Lookup |
| user_roles | 역할 → 오브젝트 1개. 지금 role = classify(기록 분류 대상) | users M-D · object_defs(CASCADE) |
기능 플래그 `CRM_FEATURE_STANDARD`·`SOURCES`(미설정 off)는 신규 시드·편입·출처 쓰기만 막는다 — 읽기·잠금은 항상. 상세: `server/README.md` 「표준·출처·기능 플래그」 절.

## 관리자 프로필·조직 기능 설정 (2026-11-12)

조직 데이터다 — `user_id` 열이 없고 계정 삭제(`DELETE_TABLES`) 대상이 아니다. 판정·변경의 정본은 `features.py`, 운영 절차는 `README.md` 「관리자 프로필·조직 기능 설정」.

| 테이블 | 역할 | 관계 |
|---|---|---|
| access_profiles | 프로필(Salesforce Profile). 기본 둘 `system_admin`·`standard_user`(`builtin`, 지울 수 없다) + 복제한 `p_<hex>`. 이름 UNIQUE | — |
| access_profile_perms | 프로필의 기능 권한 체크(행 = 켬). 시스템 관리자는 행과 상관없이 전부 | access_profiles M-D |
| org_features | 조직 기능 설정(기능마다 켜짐·꺼짐). 행 없음 = 시드 전(env == "1" 이 판정, 기본 켜짐 기능 `auto_cases` 는 env 가 비면 켜짐) | — |
| setup_changes | 변경 기록(Setup Audit Trail) — 실행자·종류·대상·전·후 값. FK 없음 | — |
| users.profile_id | 사용자 프로필(NULL = 표준 사용자). `users.role` 은 이 열의 거울(`system_admin` = admin) | access_profiles Lookup |

## 제약 검증
Governor limit 없음. M-D 깊이 최대 2(users→candidates→candidate_history). cascade 끝은 users 삭제 = 그 사용자 데이터 전체 삭제 — 계정 삭제 요청 처리와 같다. 인덱스: `(user_id, question_id, decision)`, `(user_id, created)`.

## 이관 경로 (2026-11-02)
정본: `notes/2026-11-02_이관경로-구현계획.md` K1~K10(레포 밖 비공개). 코드: `migration.py`(상태기계) · `imports.mig_apply_in`(반영 코어 — 합성 시험용 CLI `migrate_cli.py` 와 공통). 계약: `contract/imports/board-migration-2.schema.json` · 정규화 벡터 `contract/imports/vectors/board-migration-2-normalize.json`.

| 대상 | 내용 | 관계 |
|---|---|---|
| migration_tokens | 이관 전용 토큰(`mig_<id>.<secret>`, 비밀값은 SHA-256 만). 웹 세션 또는 앱 수령(PC 연결 grant)으로 발급, 14일. M2: 새 토큰을 처음 쓸 때 앞 토큰 폐기(안 쓴 대기 토큰은 다음 발급이 덮어씀) — 결국 살아 있는 1개. 일반 연결 장치 토큰(import_streams)과 분리 | users M-D |
| migration_plans | 상태 staged → sealed → applied → reverted · cancelled · expired(만든 뒤 3일). `plan_hash`(seal 때 고정) · `summary`(dry-run·영수증 개수) · 열린 plan 사용자당 3 · `via`(반영 경로 web·mcp, 옛 행 NULL) · `reverted_at`(`ck_migration_plans_reverted`). `ck_migration_plans_applied` = applied·reverted 둘 다 applied_at | users M-D |
| migration_plan_items | 받은 순 `seq` · original_id·source_revision·unit_kind·target_kind·`content_hash`·`item_sha256` · `payload`(받은 항목 JSON — 반영은 이것만 쓴다) · action(insert/noop/conflict/reject/warn)+사유 · 기준 `checked` · `result`·`target_id`(FK 없음) · `created`(반영이 대상을 새로 만들었나 — 되돌리기 판정, 옛 행 NULL) · `decision_deferred`(MCP 반영이 confirmed 표시 기준을 확정하지 않고 넣음 — 반영 뒤 미확정) | migration_plans M-D |
| records `date_kind` | 원본 날짜 종류 written·occurred·registered·heading(`ck_records_date_kind`). NULL = 라벨 없음(옛 행·이관 밖) | — |
| import_entries `reverted` | MCP `migration_revert` 가 되돌린 이관 접수 — 최신·현재 표시 없음(직전 판에 돌려준다). 판 유일성은 reverted 를 뺀 부분 UNIQUE `ux_import_revision`(옛 표 UNIQUE 는 init_schema 가 정의로 찾아 교체) — 같은 판을 다시 stage 하면 새 행. 영구 삭제 정리 뒤에도 reverted 그대로 | — |

### 판단 로그
- **사용자는 서버가 토큰으로 정한다.** 요청에 owner·user 류 필드가 오면 거절. 켜는 조건 = 스위치 `CRM_BOARD_MIGRATION_ENABLED=1` + allowlist `CRM_BOARD_MIGRATION_USERS`(user id, 기본 비어 있음) — 발급·토큰 사용·반영 때마다 본다.
- **stage 는 토큰, 확인·체크·반영은 웹 세션 — 대화(MCP) 반영은 가안 X(2026-11-02).** 반영은 stage 때 저장한 바이트만 쓴다(plan_hash 재계산 대조). 기준 체크·토큰 발급·폐기는 웹에만.
- **대화(MCP) 이관 = 가안 X** (`notes/2026-11-02_mcp-facade-이관반영-구현계획.md` §5, 레포 밖). 코드 `migration_mcp.py` — facade 이관 family op 8개(R list·get·item_get·apply_preview·receipt_get / D apply·cancel·revert). 스위치 `CRM_MIGRATION_MCP_ENABLED`(기본 꺼짐)를 읽기 포함 전부가 기존 스위치·allowlist 위에 본다. 웹과 같은 `migration.plan_apply` 에 `via` 만 다르다.
  - 규칙(MCP 경로만, 웹 불변): 기준(principle_c·wd)은 체크와 무관하게 전부 반입 · `decision=confirmed` 는 확정하지 않는다(결정 호출 없음 — 새 기준은 미확정 = `decision_deferred`, 이미 확정된 기준은 그대로: 묶음 반영이 판단 상태를 올리지도 내리지도 않음. 확정은 `item_decide(confirm)` 하나씩. 투영 해시는 받은 값 그대로 — 같은 판을 뒤에 웹으로 올려도 noop) · `decision=excluded` → 반입 안 함(`skipped_reject`, reason `decision_excluded`) · 그 기준을 가리키는 항목 = CHECK-DEPENDENCY.
  - 바인딩: `migration_apply(plan_id, plan_hash, expected_counts)` — `migration_apply_preview` 의 값과 정확히 같아야 시작(`APPLY-MISMATCH` + `detail{field, server}`). facade `decide_preview`·bind 면제(예외 1건).
  - 되돌리기 `migration_revert`(MCP 전용, 웹 API·버튼 없음): 한 트랜잭션 · 반영 뒤 대상 변화(항목 이력·연결 · 기록 후보·연결·출처 정정 · 더 새 판)가 하나라도 있으면 전체 `REVERT-MODIFIED` + `detail.seqs` · `created=true` 대상만 휴지통(168h, 휴지통 꺼짐 = SWITCH-OFF) · 출처·갱신분 유지 · 접수 reverted · plan reverted · 두 번째 호출 noop · 일일 한도는 reverted 행도 센다(돌려주지 않음).
  - 감사: 영수증 항목·최상위 `via`, `item_history.event_meta.via`(`migration_mode(via)`), `admin_audit` migration_apply detail.via·result reverted. `receipt_hash` 정의 불변.
- **dry-run = 실제 반영을 savepoint 에서 되돌린 것.** seal 결과와 반영 때 재계산이 같은 코드라 갈라지지 않는다. 반영 때 action 이 seal 과 다르면 시작하지 않고(PLAN-STALE) 전부 롤백 — 재stage.
- **출처는 신고값 그대로.** 이관 기록을 self/verbatim 으로 고정하지 않는다. 적격은 `_ELIGIBLE_SQL` 이 판정. 검토 미완·unknown·external·internal·file_mtime·URL/이메일/경로·해시 불일치는 seal 에서 reject. ai/mixed + self + verbatim 은 모순으로 reject(ai/mixed 는 verbatim 이 아닐 때만 받아 기존 SQL 로 비적격). `record_provenance_set` 은 `ingest_kind='board_migration'` 기록을 거절(PROVENANCE-MIGRATION-LOCKED) — 정정은 새 source_revision 재이관만.
- **날짜(K6).** written·occurred 시각 = `source_created_at` + created. 날짜만이거나 registered·heading = `source_date` + `date_kind`, created = 받은 시각(자정을 만들지 않는다). file_mtime 거절. 쓰지 않은 신고 날짜는 `provenance_history`. 항목(items)엔 `date_kind` 열이 없어 `generation_meta` 에 둔다.
- **멱등.** 대응표 = 기존 `import_entries`(사용자의 board_migration 입력원 하나). 같은 (original_id, source_revision) 의 다른 내용 = conflict. 같은 해시·다른 original_id = warn(distinct·supersedes 로 넘김). 출처 메타는 대응표 밖 — 자연키 (kind, name, location=anchor 해시), 같은 location 에 다른 이름이면 conflict.
- **한도.** 이관 반영 전용 200행/일(KST, `DAILY_LIMITS["migration"]` = 대응표의 오늘 적용 행 + plan 출처 적용). 일반 기록·제안·결정 집계는 이관 행을 뺀다(`_DAILY_SOURCES`). 반영은 남은 한도 < 반영 행이면 시작하지 않는다. plan 200항목 · 스테이징 사용자당 2MB · 청크 256KB · 토큰 분당 60 요청.
- **원문 체류 최소화.** 항목 본문(payload)은 reject 면 seal 때, 반영·취소·만료 때 바로 영구 삭제(휴지통 아님). 남는 것은 해시·action·결과·대상 id(영수증). 만료 정리 = `imports.expire_pending` 회차 + 접근 때 즉시.
- **CLI 은퇴.** `migrate_cli.py` run·resume·close 는 DB 이름이 crm_test* 일 때만(합성 시험). 운영 이관은 위 경로.

## PC 연결·토큰 대화 발급 (2026-11-02 가안 2 「상주 앱 수령형」)

정본: `notes/2026-11-02_pc-connect-구현계획.md`(비공개). 코드: `token_grants.py`. 토큰이 대화에 남지 않게 — 대화(MCP)는 「이 PC 로 보내라」만 남기고,
같은 계정으로 로그인한 앱이 세션 + `X-MyCRM-Desktop` 헤더로 받아 간다. 토큰은 수령 요청 안에서 발급되고 그 응답에만 있다.

| 오브젝트 | 뜻 | 관계 |
|---|---|---|
| desktop_installations | 설치본 = 로그인한 앱 하나(`di_<hex24>`, 앱 userData 에 보관). `client_name`·`os`(darwin·win32·linux)·`last_login_at`(지목 기본)·`last_seen_at`(폴링 — 최근 2분 = 켜짐)·`revoked_at`(대화 `pc_forget` 해제 기록 — 자동 연결·교체가 되살리지 않는다)·`device_id`(이 PC 의 연결 장치, FK 없음). IP·호스트·경로 없음. 계정당 해제 안 된 것 10 | users M-D |
| token_grants | 전달 요청(`tg_<hex24>`) — `scope` device·migration · `state` waiting → delivered(redeem) · expired(10분) · cancelled(pc_forget) · `via`=mcp · `delivered_to`(받은 장치·PC 이름). 토큰 값·해시 열 없음. 한도: 계정당 열린 3·하루(KST) 10. 정리 회차가 만료 표시·30일 지난 끝난 행 삭제 | desktop_installations M-D (cascade) |
| import_streams.pending_* | M2 대기 토큰(`pending_token_id`·`pending_secret_hash`·`pending_expires_at`, 부분 UNIQUE·`ck_import_streams_pending`) — 재발급·교체·자동 연결의 새 토큰. 처음 인증되면 현재 토큰으로 올라가고 옛 토큰은 그때 무효. 1개(다음 교체가 덮어씀). 만료 지난 대기 토큰은 정리 회차가 비운다 | — |

### 판단 로그
- **수령 관문 = 앱 세션 바인딩.** 서버는 사용자 발화를 확인할 수 없다(MCP elicitation 불가). 그래서 토큰은 같은 계정 앱 세션 + 헤더로만 받는다. 대화 쪽은 W(`pc_connect`)·D(`migration_token_send`·`pc_forget`·`token_revoke`, bind)·한도·규칙 문장뿐 — prompt injection 피해 상한 = 내 PC 에 내 장치 토큰(사용자 데이터 읽기 없음).
- **M2 「새 토큰 첫 사용 때 무효」.** 업로드가 `run-once` 때만이라 시간 유예는 새 토큰을 죽일 수 있다. 장치 = 대기 열, 이관 = 행마다 토큰이라 「안 쓴(last_used_at NULL) 앞 토큰은 발급 때 폐기 · 새 토큰 첫 인증 때 나머지 폐기」. 웹 재발급·이관 웹 발급도 같다.
- **해제 기록은 서버가 지킨다.** 앱 userData 를 지워도 서버 설치본 표·장치 표의 해제가 남아 자동 연결(`/desktop/device/auto`)·교체가 `DEVICE-REVOKED`. 다시 연결은 대화(`pc_connect` → redeem)에서만.
- **M3 계정 전환.** 다른 계정 설치본·grant 는 `NOT-OWNER` — 앱이 옛 계정 장치 토큰을 지우고 새 계정으로 다시 등록.

## `db.py` psycopg 판 메모(옛 SQLite 임시판과의 차이)
Postgres 전환은 끝났다(2026-10-18, `db.py` psycopg 판). 후보 revision 검사는 PR① 에서 웹 결정에 넣었다(`expected_revision`). 남은 것(지인 검증 전): 같은 본문 10분 중복 억제, `state_get` 요약+커서, 입력 상한 거절. 토론 raw 는 세션 스크래치패드 `arch/`.

## 수기 수정 A0′ (2026-11-03)
계약 문장: **내가 결정한 판단이 붙지 않은 글은 고칠 수 있다. 고친 흔적은 이력에 남는다.** 근거: 레포 `notes/2026-11-03_React전환-구현계획.md` §5-1(gitignore).

| 대상 | 컬럼 | 뜻 |
|---|---|---|
| records | `revision`(1부터) | 본문·제목 수정마다 +1. 옛 행은 1(`db._migrate_record_edit`) |
| record_history | `action` edit/title · `prev_revision` · `change` jsonb · `via` web/mcp | 한 줄 = revision +1(`UNIQUE(user_id,record_id,prev_revision)`). edit = `{start, old, new, deleted_candidates, moved_candidates}`(start = 고치기 전 본문의 코드포인트 오프셋) · title = `{old, new}`. 기록과 같이 지워진다 |

- 본문: 대화 `record_edit(record_id, expected_revision, old, new)`(facade decide — `decide_preview` 의 shown = 전·후 + 지워질 미결 후보 수, bind 필수). `old` 는 원문에 정확히 한 번(겹침 포함) — 0번 `EDIT-NOT-FOUND`, 2번 이상 `EDIT-AMBIGUOUS`(앞뒤를 포함해 더 길게). 웹 `POST /api/records/{id}/body` 는 새 본문 전체를 받아 공통 앞·뒤를 뺀 한 구간으로 같은 서버 함수(`db._edit_apply`)를 부른다.
- 제목: `record_title_set`(facade write) · 웹 `POST /api/records/{id}/title`. 판단 잠금과 무관(제목은 인용 근거가 아니다). 같은 제목은 no-op.
- 막힘: 휴지통 안(`IN-TRASH`) · `author_kind=external`(`RECORD-LOCKED`) · 확정·남기지 않음 후보가 붙은 글의 본문(`RECORD-LOCKED` — 고친 글은 새 기록으로) · revision 다름(`CONFLICT`). 행 잠금(users → records)으로 후보 생성·출처 정정과 직렬화한다.
- 미결 후보(다시 뽑을 수 있는 제안 — 휴지통·복원 없음): 변경 구간 [s, e)(고치기 전 본문)와 겹치거나 닿으면(`quote_start <= e` 이고 `quote_end >= s`) 지운다 — 지울 후보 중 하나라도 기준·항목 연결(`item_links`)이 걸려 있으면 수정 전체를 `RECORD-LOCKED`(관계는 사용자 결정) · 앞이면 그대로 · 뒤면 `quote_start`·`quote_end` 에 delta(새 길이 − 옛 길이)를 더한다. 옮긴 뒤 새 본문[quote_start:quote_end] ≠ quote 면 지운다. 옮기기는 한 행씩(늘면 뒤에서부터·줄면 앞에서부터)이라 UNIQUE 순간 충돌이 없다. 미리보기 shown = 「검토할 판단 N개가 지워져요(다시 뽑을 수 있어요)」(N = 지울 수, 0이면 줄 없음).
- 그대로인 것: 출처 판정(self·verbatim 적격 유지) · notes(「어디에 붙나」)·색인 재계산 없음 · 일일 기록 한도(새 기록이 아니다) · 「오타만」 범주 없음(서버가 판정하지 못한다).
- 출처 정정 이력(`provenance_history`) 한 줄에도 `via`(web/mcp).
- 항목(기준·결정·축·커스텀) 웹 인라인 편집: `POST /api/item/edit` = `db.item_edit` = `item_propose` + `item_decide(apply)` 한 트랜잭션(`tx_scope`) — expected_revision·code 불변·관계 검증 그대로, `item_history` 한 줄. 확정 기준의 문장을 고쳐도 확정 유지. 대화는 새 op 없이 `item_propose` → `item_decide(apply)`.

## 레이아웃 계약 v2 (2026-11-03)
- 정본 = `server/layout_registry.json` 한 곳: `components`(id → label·허용 영역 `regions`·`props` 모양 `{type: string|integer|boolean, enum?, max?}`) · `pages`(페이지 → 영역 목록·`default`). `db.DEFAULT_LAYOUT` 은 이 파일에서 만든다(사본 없음). 화면(TS)도 같은 파일을 읽는다.
- 모양: `{"v": 2, "pages": {페이지: {"tabs": 기본 탭의 순열, "regions": {영역: [{"c": 컴포넌트, "p": {props}}]}}}}`. 영역마다 허용된 컴포넌트만·중복 없이(빼기는 된다). 모르는 키 `LAYOUT-INVALID`. JSON 상한 8192 바이트.
- v1 행(`{"v":1,"tabs","blocks"}`)은 읽을 때 v2 로 올려 돌려준다(쓰기 없음). 다음 저장부터 v2. v1 모양 저장은 거절.
- 대화: `layout_get`(read) · `layout_set(page, layout, version)`(write — 그 페이지만 바꾼다) · `layout_reset(page)`(write). 웹 `GET·PUT·DELETE /api/me/layout` 은 v2 전체. 버전 불일치 `LAYOUT-STALE`.


## 웹 대화 확인 카드, PC 허용 거절 (2026-11-11 대화 하나로 F)
- 표 정의는 `schema.sql` 의 `chat_approvals`, `chat_provider_grants`. 두 열은 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 로 schema.sql 안에 있다 — 서버 시작(`main.lifespan` → `db.init_schema`)이 schema.sql 전체를 실행하므로 운영 DB 에도 그때 붙는다. 옛 행은 기본값(아래)으로 읽힌다.
- `chat_approvals.kind`(`decide`, `write`, 기본 `decide`): 카드 종류. 옛 행은 decide 다.
  - decide 카드 = 기존 그대로(`CHAT_APPROVABLE_OPS` 10개, facade `decide_preview` 와 같은 preview, bind).
  - write 카드 = 자유 대화의 write 등급 op 전부(`pc_connect` 제외 14개, 판정은 `chat_mcp._PINNED_TIERS` 등급). 모델이 부르면 실행하지 않고 카드만 만든다. `params` = facade 검증, 정규화를 거친 값, `preview` = `{op, shown, impact:{tier:"write"}, irreversible:false, hash}`. shown 은 정규화 params 의 모든 키(아는 키는 한국어 이름표, 모르는 키는 키 이름, 값은 자르지 않음). hash = sha256(op ∥ 정규화 params). facade PREVIEWS, bind 와 무관하다.
  - 확정(웹 카드)은 저장한 params 를 다시 정규화해 hash, shown 이 같을 때만 `facade.dispatch("write", …)` 로 실행한다. 다르면 `APPROVAL-STALE`. 한 번만 확정, 한도(대기 20, 세션 100행, 600초)는 decide 와 같다.
  - 덮어쓰기 카드(2026-11-11 I 반영 R1~R3): 대상이 이미 있는 write 는 서버가 대상의 지금 상태를 DB 에서 읽어 shown = `{"지금": 지금 상태, "바뀐 뒤": 위 정규화 params 줄}` 로 둔다. hash = sha256(op ∥ 정규화 params ∥ 지금 상태). 확정 때 같은 트랜잭션(users 행 잠금, 대상 행 FOR UPDATE)에서 다시 읽어 다르면 `APPROVAL-STALE`. 대상 판별은 op별 읽기 함수 표 `webchat._WRITE_CURRENT`(layout_set, layout_reset, display_name_set, profile_set, record_attach, record_title_set, definition_propose, item_propose·person_save·source_reflection_save 는 id 가 있을 때, definition_propose 는 object_id 가 없어도 같은 key 의 미적용 행이 있을 때). 새로 만들기만 하는 op(`_WRITE_CREATE_ONLY`: question_add, record_add, candidates_propose, source_create)은 위 평평한 shown 그대로. 두 표 밖의 write op 은 카드를 만들지 않는다. 대상이 없거나 휴지통이면 지금 = 고정 표지. 지금 값은 카드(웹)에만 있고 모델 응답에는 없다. 그래서 카드 행(30일 보관)에 덮이기 전 값(예: 읽고 든 생각 본문)도 남는다.
- PC 허용 기록 30일 정리(I 반영 R8): `webchat.purge`(main.purge_once 회차)가 생성 30일 지난 `chat_consent_challenges`, `chat_provider_grants`(남은 challenge 는 FK CASCADE)를 지운다. `desktop_consent_keys` 는 폐기(`revoked_at`) 또는 pending PoP 만료(`pop_expires_at`) 뒤 30일 지난 것만 지운다. active 키는 지우지 않는다. (2026-11-12 J 뒤) 세션 동의는 grant 가 아니라 서 있는 허용(`chat_provider_permits`, 아래 절)이 정하므로 이 정리는 세션을 닫지 않는다. 서 있는 허용은 30일 정리 대상이 아니다.
- 대화 요청 속도(I 반영 R4): `POST /api/chat/launch-authorization`, `POST /api/chat/mcp` 는 접수 요청 버킷(`imports._rate`, `bucket='request'`)을 쓰지 않는다. 같은 `import_counters` 표에 버킷 `chat_launch`(장치 분당 60), `chat_mcp`(장치 분당 60)로 센다. 사용자 합계는 버킷마다 장치 상한의 2배(120, 120). 넘으면 429 `RATE-LIMIT`. 분 카운터 매시 정리는 버킷과 무관하다.
  - 다음 턴 outcomes = `{id, op, status, created?}`. created 는 확정된 write 의 생성 id 만(op별 허용 키 `id`, `source_id`, `object_id`, `proposal_id`, `item_id`, 값은 생성기 모양 정규식). 글이나 그 밖의 값은 넣지 않는다.
  - outcomes 크기(F13): 최신 행부터 담고, agent 꼴 JSON(압축) 바이트가 `APPROVAL_OUTCOMES_JSON_MAX`(13 KiB)를 넘기 전에서 오래된 행을 뺀다. 개수 상한 100 그대로. agent 고정 문구 + 이 값 <= 16 KiB - 1 KiB 를 시험이 대조한다.
- `chat_provider_grants.close_reason`(NULL, `declined`, `locked`, `failed`): PC 앱이 동의 창이 허용 없이 끝났다고 장치 WS `consent.result` 로 알린 이유. 그 연결의 사용자, 장치의 pending grant 에만, 처음 한 번만 쓴다(멱등). 쓰면서 그 grant 의 issued challenge 를 revoked 로 바꾼다. 값이 있는 grant 는 challenge 발급, 서명 검증, 소비가 모두 거절된다. 상태 조회 prompt: declined → `declined`, locked, failed → `closed`. state CHECK 는 그대로(pending 행에 이유만 붙는다). 상태 조회는 `close_reason` 도 그대로 돌려준다(2026-11-12 J-F2: 화면이 failed = 허용 창을 못 띄움, locked = 화면 잠김, declined = 허용 안 함을 나눠 말한다).


## 웹 대화 서 있는 허용 (2026-11-12 대화 하나로 J, JD1~JD3)
- 앱 하나 1.3(2026-11-13): `chat_provider_permits.basis`(consent | device). device = 새 앱이 WS hello `ai_links` 로 알린 공급자 인증(linked)으로 세운 허용 — 서명 근거 넷(installation_id, key_id, grant_id, challenge_id) NULL(`ck_chat_provider_permits_basis`). 살아 있음 = 장치 토큰 유효. 옛 DB 는 `db._migrate_device_permits`(열 추가, NOT NULL 풀기).
- 표 `chat_provider_permits`(새 표, `CREATE TABLE IF NOT EXISTS`)와 `chat_sessions.permit_id`(`ADD COLUMN IF NOT EXISTS`, NULL 허용). 서버 시작(`main.lifespan` → `db.init_schema`)이 schema.sql 전체를 실행하므로 운영 DB 에도 그때 생긴다. 계정 삭제 = `db.DELETE_TABLES`.
- 단위: (사용자, 장치, 공급자) 하나에 한 행(`UNIQUE (user_id, device_id, provider)`). 모델은 단위가 아니다. Claude 를 한 번 허용하면 그 PC 에서 Claude 의 어느 모델이든, 새 대화든 다시 묻지 않는다. Codex 는 따로 한 번.
- 성립: 첫 세션이 서명 검증된 grant 를 `session_new` 에서 소비할 때(지금과 같은 조건: PC 동의 창 허용, Ed25519 검증, 동의 키 active) 그 grant 의 verified challenge 로 행을 세운다. 열: `installation_id`, `key_id`, `grant_id`, `challenge_id`(성립 근거 식별자, FK 없음 — grant, challenge 는 30일 정리로 사라진다), `created_at`. 다시 세우면 새 id(옛 행에 묶인 세션은 살아나지 않는다). 기본 모델(grant.model = null)도 허용을 세운다. 서명 claims 의 model 은 문자열이어야 해서 null 을 표지 `:default`(`webchat.CONSENT_DEFAULT_MODEL`)로 서명하고 challenge 행에도 그 값을 둔다. 표지는 서버 내부 값이라 ':'로 시작하는 모델 이름은 grant 요청, 세션 생성, 세션 생성(`MODEL_RE`)에서 받지 않고, PC 가 알린 선택지에서는 그 모델 하나만 뺀다(R-J1).
- 판정(`webchat._permit_live`, 하나뿐): 행이 있고 세션이 묶인 그 id 이며, 장치가 연결 중(해제, 토큰 폐기, 토큰 만료 아님), `key_id` 키가 같은 사용자, 설치본, 장치의 active 키, 설치본이 해제되지 않고 같은 장치에 묶였을 때만 살아 있다. 쓰는 곳: `session_new`(살아 있으면 grant 없이 세션), 세션 재확인(턴 만들기, 확인 카드 확정), `launch-authorization`(binding 의 `grant_id`, `consent_challenge_id` = 허용 성립 근거), `/api/chat/mcp`, capabilities(`allowed_providers`), `GET /api/chat/permits`. `permit_id` 가 없는 J 이전 세션은 닫힌 실패(`CONSENT_REQUIRED`)다.
- 키 회전: PC 앱은 동의 창마다 키를 begin, activate 로 회전한다. activate 가 옛 키 서명(rotate)으로 이어짐을 증명하면 그 키에 선 허용을 새 키로 옮긴다(`key_id` 갱신). 그래서 다른 공급자의 동의 창이나 거절이 서 있는 허용을 죽이지 않는다.
- 끝: 사람이 하는 해제 `POST /api/chat/permits/revoke {device_id | installation_id, provider: claude|codex|null}`(웹 쿠키 + Origin, 장치 토큰 없음, 남의 장치, 설치본 = 404, 멱등), PC 연결 해제(`imports.revoke_in`: 웹 장치 해제, `pc_forget`), 설치본 해제(`pc_forget`), 웹 토큰 재발급(`device_reissue`), 키 폐기(`keys/revoke`, 그 설치본 전부), 만료되거나 폐기된 토큰을 새 토큰으로 바꿀 때(`imports.pending_in`). 토큰 만료 자체는 판정 실패다. 살아 있는 토큰의 교체(agent 자동 rotate)는 허용을 지우지 않는다. 화면 잠금과 앱 재시작은 허용을 지우지 않는다(JD2, 원작자 위험 수용).
- 사람이 하는 해제(`permit_revoke`)는 지운 (장치, 공급자)의 열린 세션을 같은 트랜잭션에서 닫는다(실행 중 턴 = failed `CONSENT_REQUIRED`). route 는 커밋 뒤 그 턴마다 PC 에 `turn.stop` 을 보낸다(R-J2). 그 밖의 끝(장치 해제, 토큰 만료 등) 뒤 열린 세션은 다음 재확인(턴, 확인 카드, launch-authorization 5초 주기, `/api/chat/mcp`)에서 거절된다.
- 보관: 쓰는 동안 남는다(30일 정리 대상 아님). 처리방침의 "PC 허용 기록 30일" 문구와 다르다(PR #64, 메인이 고친다).
