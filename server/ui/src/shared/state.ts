// /api/state 에서 옮긴 화면이 읽는 조각의 타입(손 사본). 서버 정본 = server/web.py api_state·db.state.
// 견본 state.sample.json 을 서버 시험(test_web_home.py test_state_sample)이 실제 응답과 대조하고, tsc 가 satisfies AppState 로 묶는다.
import type { Agg } from "./activity";

export type Link = { field_key: string; target_kind: string; target_id: string };
export type RecLink = Link & { record_id: string };
export type Rec = {
  id: string; title: string | null; excerpt: string; created: string; source: string | null;
  source_id: string | null; question_id: string | null; source_date: string | null; author_kind: string;
  ingest_kind: string | null;   // inbox = 저장 승인 대기에서 승인해 들어온 글(「오늘」)
  broken?: boolean;             // 읽지 못한 글(부분 읽기 실패 행)
};
export type Question = { id: string; text: string; created: string };
export type Cand = {
  id: string; text: string; status: string; record_id: string; question_id: string | null;
  quote: string; review: string | null; revision: number; created: string;
  origin: string; edited_by_user: boolean; wording_by: string | null; wording_approved: boolean;
};
// proposal = 적용 전 제안(새 항목이면 revision 0 + 제안만) · promotion = 승격 조건 사실(기준만 — 남길지는 사용자)
export type Proposal = { proposal_id: string; title?: string | null; body?: string | null; code?: string | null;
  data?: Record<string, unknown> | null; links?: Link[]; proposed_at?: string };
export type Promotion = { met: boolean; confirmed_claims: number; confirmed_claims_min: number; distinct_events?: number; distinct_events_min?: number };
export type Item = {
  id: string; object_id: string; code: string | null; title: string | null; body: string | null;
  data: Record<string, unknown> | null; decision: string | null; revision: number; semantic_kind: string;
  proposal: Proposal | null; links: Link[]; created_at: string; updated_at: string; promotion?: Promotion | null;
};
export type Field = { key: string; label: string; value_type: string; options: { value: string; label: string }[]; target_object_id?: string | null };
export type Def = { id: string; key: string; label: string; semantic_kind: string; std_id: string | null; archived_at: string | null; fields: Field[];
  policy?: { promotion?: { claim_field?: string; event_field?: string } | null } | null };
export type Person = { id: string; alias: string; revision: number; created: string; updated: string };
export type Refl = { id: string; source_id: string; kind: string; body: string; review: string; revision: number; created: string; updated: string; reviewed_at: string | null };
export type Source = { id: string; kind: string; name: string; location: string | null };

// 대화 서랍 — 이어 받을 세션(확정 전·만료 전 최신 1) · 내 장치 상태(서버 판정 그대로, 화면은 state·last_seen_at 만 읽는다)
export type StackSession = { id: string; expires_at: string };
export type DevicesStatus = { state: string; last_seen_at: string | null; threshold_seconds: number };

// 사용자 탭(질문형·기록형 — blocks[0] = journal 이면 기록형) · 자료 종류 카드(구조 정의 요약)
export type Tab = { id: string; label: string; blocks: string[] };
// 구조 정의(서버 contract.respond 본인 응답 — origin·locked·cardinality 는 서버 판정, 화면이 다시 판정하지 않는다)
export type StructField = { key: string; label: string; value_type: string; origin: string; locked: boolean; std_name?: string | null };
export type StructObj = { id: string; key: string; label: string; origin: string; semantic_kind?: string; locked?: boolean; std_name?: string | null; fields?: StructField[] };
export type StructRel = { object_id: string; field_key: string; target_kind: string; target_object_id: string | null; cardinality: string; origin: string; locked: boolean };
// 다음 할 일 한 줄(서버 next_action) · 출처 라벨(structure_svg ORIGIN_TEXT·ORIGIN_CATEGORY 정본 — 서버가 내려 준다)
export type Next = { kind: string; text: string };
export type OriginLabels = { text: Record<string, string>; category: Record<string, string> };

export type AppState = {
  generated?: string;   // 서버가 상태를 만든 시각(ISO) — 바닥 「불러온 시각」
  user: { display_name: string | null; nav: string; email?: string; struct_names?: boolean; admin?: boolean };   // admin = 관리자일 때만 true(서버 Q1 strip 과 같은 조건)
  switches: { trash: boolean; converse?: boolean };
  read?: Record<string, { ok: boolean; error?: { code: string; msg: string } }>;   // 부분 읽기 실패 때만 온다
  stack_session?: StackSession | null;
  devices_status?: DevicesStatus;
  journal: Rec[];
  journal_next_before: string | null;
  questions: Question[];
  candidates: Cand[];
  items: Item[];
  item_proposals: Item[];
  definitions: Def[];
  record_links: RecLink[];
  people: Person[];
  reflections: Refl[];
  sources: Source[];
  source_counts: { by_source: Record<string, number>; unconfirmed: number };
  activity_ui: { actions: Record<string, string>; providers: Record<string, string>; pending_days: number };
  activity?: Agg | null;   // 활동 현황 30일(본인) — 활동 부분 읽기 실패면 null(read.activity)
  tabs: Tab[];
  structure: { objects: StructObj[]; relations?: StructRel[]; core?: { kind: string; origin: string }[] };
  structure_svg?: string;          // 같은 응답의 구조 그래프(서버 structure_svg.render) — 화면은 React 요소로 옮겨 그린다(HTML 문자열 꽂기 0)
  origin_labels?: OriginLabels;
  next?: Next | null;
  me: { counts: Record<string, number> };   // 「나」 개수(people·sources·reflections …) — 서버 home counts 그대로
  inbox?: { pending: number } | null;            // 저장 승인 대기 수(장치 가져오기를 쓰는 계정만)
};

// 부분 읽기 실패(S.read[part].ok=false)면 그 조각은 없는 것 — 옛 app.html ok() 와 같다
export const readOk = (S: AppState, part: string) => !S.read || !S.read[part] || S.read[part].ok;
