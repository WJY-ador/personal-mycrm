// /api/state 에서 옮긴 화면이 읽는 조각의 타입(손 사본). 서버 정본 = server/web.py api_state·db.state.
// 견본 state.sample.json 을 서버 시험(test_web_home.py test_state_sample)이 실제 응답과 대조하고, tsc 가 satisfies AppState 로 묶는다.
import type { Agg } from "./activity";

export type Link = { field_key: string; target_kind: string; target_id: string };
export type RecLink = Link & { record_id: string };
export type Rec = {
  id: string; title: string | null; excerpt: string; created: string; source: string | null;
  source_id: string | null; question_id: string | null; source_date: string | null; author_kind: string;
  ingest_kind: string | null;   // inbox = 저장 승인 대기에서 승인해 들어온 글(「오늘」)
};
export type Question = { id: string; text: string; created: string };
export type Cand = {
  id: string; text: string; status: string; record_id: string; question_id: string | null;
  quote: string; review: string | null; revision: number; created: string;
  origin: string; edited_by_user: boolean; wording_by: string | null; wording_approved: boolean;
};
export type Item = {
  id: string; object_id: string; code: string | null; title: string | null; body: string | null;
  data: Record<string, unknown> | null; decision: string | null; revision: number; semantic_kind: string;
  proposal: { proposal_id: string } | null; links: Link[]; created_at: string; updated_at: string;
};
export type Field = { key: string; label: string; value_type: string; options: { value: string; label: string }[] };
export type Def = { id: string; key: string; label: string; semantic_kind: string; std_id: string | null; archived_at: string | null; fields: Field[] };
export type Person = { id: string; alias: string; revision: number; created: string; updated: string };
export type Refl = { id: string; source_id: string; kind: string; body: string; review: string; revision: number; created: string; updated: string; reviewed_at: string | null };
export type Source = { id: string; kind: string; name: string; location: string | null };

// 대화 서랍 — 이어 받을 세션(확정 전·만료 전 최신 1) · 내 장치 상태(서버 판정 그대로, 화면은 state·last_seen_at 만 읽는다)
export type StackSession = { id: string; expires_at: string };
export type DevicesStatus = { state: string; last_seen_at: string | null; threshold_seconds: number };

// 사용자 탭(질문형·기록형 — blocks[0] = journal 이면 기록형) · 자료 종류 카드(구조 정의 요약)
export type Tab = { id: string; label: string; blocks: string[] };
export type StructObj = { id: string; key: string; label: string; origin: string };

export type AppState = {
  user: { display_name: string | null; nav: string };
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
  structure: { objects: StructObj[] };
  me: { counts: Record<string, number> };   // 「나」 개수(people·sources·reflections …) — 서버 home counts 그대로
  inbox?: { pending: number } | null;            // 저장 승인 대기 수(장치 가져오기를 쓰는 계정만)
};

// 부분 읽기 실패(S.read[part].ok=false)면 그 조각은 없는 것 — 옛 app.html ok() 와 같다
export const readOk = (S: AppState, part: string) => !S.read || !S.read[part] || S.read[part].ok;
