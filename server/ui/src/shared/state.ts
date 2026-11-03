// /api/state 에서 옮긴 화면이 읽는 조각의 타입(손 사본). 서버 정본 = server/web.py api_state·db.state.
// 견본 state.sample.json 을 서버 시험(test_web_home.py test_state_sample)이 실제 응답과 대조하고, tsc 가 satisfies AppState 로 묶는다.
export type Link = { field_key: string; target_kind: string; target_id: string };
export type RecLink = Link & { record_id: string };
export type Rec = {
  id: string; title: string | null; excerpt: string; created: string; source: string | null;
  source_id: string | null; question_id: string | null; source_date: string | null; author_kind: string;
};
export type Question = { id: string; text: string; created: string };
export type Cand = {
  id: string; text: string; status: string; record_id: string; question_id: string | null;
  quote: string; review: string | null; revision: number; created: string;
};
export type Item = {
  id: string; object_id: string; code: string | null; title: string | null; body: string | null;
  data: Record<string, unknown> | null; decision: string | null; revision: number; semantic_kind: string;
  proposal: { proposal_id: string } | null; links: Link[]; created_at: string; updated_at: string;
};
export type Field = { key: string; label: string; value_type: string; options: { value: string; label: string }[] };
export type Def = { id: string; key: string; label: string; std_id: string | null; archived_at: string | null; fields: Field[] };
export type Person = { id: string; alias: string; revision: number; created: string };
export type Refl = { id: string; source_id: string; kind: string; body: string; review: string; revision: number; created: string; updated: string };
export type Source = { id: string; kind: string; name: string; location: string | null };

export type AppState = {
  user: { display_name: string | null; nav: string };
  switches: { trash: boolean };
  read?: Record<string, { ok: boolean }>;   // 부분 읽기 실패 때만 온다
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
  activity_ui: { actions: Record<string, string> };
};

// 부분 읽기 실패(S.read[part].ok=false)면 그 조각은 없는 것 — 옛 app.html ok() 와 같다
export const readOk = (S: AppState, part: string) => !S.read || !S.read[part] || S.read[part].ok;
