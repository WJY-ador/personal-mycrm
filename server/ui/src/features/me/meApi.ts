// 「나」 서버 접점 — 읽기(통계·레이아웃·기록 본문·이어 받기·문맥) + 쓰기(기존 경로 + 수기 수정). 응답 모양 정본 = server/web.py·db.py.
// 견본 대조 = me.sample.json(stats·layout·journal) ↔ server/test_web_home.py test_me_samples.
import { deleteJSON, getJSON, postJSON, putJSON } from "../../shared/api";
import { itemDecide, trashMove, type ItemDecide } from "../../shared/item";
import { candidateDecide, fetchJournal, type CandDecide } from "../../shared/journal";
import type { Act } from "../../shared/activity";
import { axisParam } from "../../shared/axes";
import type { Rec } from "../../shared/state";

export type { Journal } from "../../shared/journal";

export type Stats = {
  axes: { id: string; code: string | null; title: string; items: number; records: number; readings: number; n: number }[];
  heatmap: { from: string; to: string; cells: { d: string; records: number; activities: number }[] };
  kinds: Record<string, number>;
  waiting: Record<string, number>;
};
export type Slot = { c: string; p: Record<string, unknown> };
export type MePage = { tabs: string[]; regions: Record<string, Slot[]> };
export type Layout = { layout: { v: number; pages: { me: MePage } }; version: number };
export type BodyPreview = { record_id: string; revision: number; before: string; after: string; drop: number; msg: string };
export type { Act } from "../../shared/activity";
export type PersonCtx = { activities: Act[]; activity_count: number; records: { id: string; title: string | null }[];
  items: { id: string; object_id: string; title: string | null; field_key: string }[] };
export type AxisCtx = { activities: Act[]; activity_count: number };
export type SourceCtx = { activity_count: number; by_action: { action: string; label: string; n: number }[]; activities: Act[] };

// 오브젝트 탭 목록 보기(GET /api/me/objects/<key>, 50행씩) — 응답 모양 정본 = server/db.py object_list
export type ObjCol = { key: string; label: string; value_type: string; options: { value: string; label: string }[] };
// axes = 그 행의 축(수집 글 행만, 축 잇기 — 코드 칩)
export type ObjRow = { id: string; code: string | null; title: string; revision: number; updated_at: string; data: Record<string, unknown>; state?: string;
  axes?: { id: string; code: string | null; title: string | null }[] };
export type ObjList = {
  object: { id: string; key: string; label: string }; columns: ObjCol[]; has_state: boolean; sort: { key: string; dir: "asc" | "desc" };
  filters: { key: string; label: string; values: { value: string; label: string; n: number }[] }[]; states: Record<string, number> | null;
  rows: ObjRow[]; total: number; next_cursor: string | null;
};
export type ObjQuery = { sort: string; dir: string; q: string; f: Record<string, string>; state: string; axis?: string };   // axis = 축 화면의 축 item id
const objParams = (p: ObjQuery, cursor: string) => {
  const u = new URLSearchParams();
  for (const [k, v] of [["sort", p.sort], ["dir", p.dir], ["q", p.q.trim()], ["state", p.state], ["cursor", cursor]]) if (v) u.set(k, v);
  for (const [k, v] of Object.entries(p.f)) if (v) u.set("f." + k, v);
  if (p.axis) u.set(...axisParam(p.axis));
  const s = u.toString();
  return s ? "?" + s : "";
};

const enc = encodeURIComponent;
export const meApi = {
  stats: () => getJSON<Stats>("/api/me/stats"),
  layout: () => getJSON<Layout>("/api/me/layout"),
  // 페이지 레이아웃(Setup) — v2 전체를 보낸다 · version 불일치 = 409 LAYOUT-STALE · DELETE = 기본으로 되돌리기(version +1)
  layoutPut: (me: MePage, version: number) => putJSON<Layout>("/api/me/layout", { layout: { v: 2, pages: { me } }, version }),
  layoutReset: () => deleteJSON<Layout>("/api/me/layout"),
  journal: fetchJournal,
  records: (before: string) => getJSON<{ records: Rec[]; next_before: string | null }>(`/api/records?before=${enc(before)}&limit=50`),
  person: (id: string) => getJSON<PersonCtx>(`/api/people/${enc(id)}/context`),
  axis: (id: string) => getJSON<AxisCtx>(`/api/axes/${enc(id)}/context`),
  source: (id: string) => getJSON<SourceCtx>(`/api/sources/${enc(id)}/context`),
  activity: (id: string) => getJSON<Act>(`/api/activities/${enc(id)}`),
  objList: (key: string, p: ObjQuery, cursor = "") => getJSON<ObjList>(`/api/me/objects/${enc(key)}${objParams(p, cursor)}`),
  // 쓰기 — 기존 경로
  name: (display_name: string) => postJSON("/api/me/name", { display_name }),
  reflection: (id: string, body: object) => postJSON(`/api/reflections/${enc(id)}`, body),
  review: (id: string, reviewed: boolean, expected_revision: number) => postJSON(`/api/reflections/${enc(id)}/review`, { reviewed, expected_revision }),
  candidate: (body: CandDecide) => candidateDecide(body),
  itemDecide: (body: ItemDecide) => itemDecide(body),
  trash: trashMove,
  // 쓰기 — 수기 수정(A0′, R2)
  recordTitle: (id: string, expected_revision: number, title: string) => postJSON(`/api/records/${enc(id)}/title`, { expected_revision, title }),
  recordBody: (id: string, expected_revision: number, body: string) => postJSON(`/api/records/${enc(id)}/body`, { expected_revision, body }),
  // 본문 저장 전 미리보기(쓰기 없음, 저장과 같은 판정) — msg = 지워질 검토할 판단이 있을 때만 서버 문구(없으면 "")
  recordBodyPreview: (id: string, expected_revision: number, body: string) =>
    postJSON<BodyPreview>(`/api/records/${enc(id)}/body/preview`, { expected_revision, body }),
  itemEdit: (item_id: string, expected_revision: number, title: string, body: string) =>
    postJSON("/api/item/edit", { item_id, expected_revision, title, body }),
  // 자동 분류(2026-11-18 구조추천) — 근거 원문(읽기, text = 서버가 자른 단위 구간 그대로) · 빼기(항목을 지우고 그 원문 단위를 예외로)
  routeItem: (id: string) => getJSON<{ item: RouteInfo | null }>(`/api/route/item?id=${enc(id)}`),
  routeExclude: (item_id: string, expected_revision: number) => postJSON("/api/route/exclude", { item_id, expected_revision }),
  hint: () => getJSON<{ show: boolean }>("/api/structure/hint"),   // 나 탭 요약 추천 한 줄(서버가 건수만 싸게 센다)
  // 루틴판(2026-11-21) — 블록 설정 p 는 서버가 저장된 레이아웃에서 읽는다(화면이 보내지 않는다). 읽기만
  routine: () => getJSON<Routine>("/api/me/routine"),
  routineDetail: (id: string) => getJSON<RoutineDetail>(`/api/me/routine/${enc(id)}`),
};
export type RouteInfo = { item_id: string; object_id: string; record_id: string; record_title: string | null; unit_key: string; start: number; end: number; text: string | null };

// 루틴판 집계(GET /api/me/routine) · 한판 상세(GET /api/me/routine/<id>) — 응답 모양 정본 = server/db.py routine_board·routine_board_detail.
// kind 는 JSON 견본 대조 때문에 string 으로 둔다(item|record, post|record). AI 값은 상세의 수집 글 ai_summary 하나뿐(ai = true)
export type RoutineLine = { date: string | null; text: string; target: { kind: string; id: string; object_key: string; item_id?: string | null } };
type RoutineCol = { lines: RoutineLine[]; more: number; unrefined: number };
export type RoutineCard = { item_id: string; key_line: string; date: string | null; n_subheads: number; n_sources: number };
export type Routine = {
  ready: boolean; missing: string[]; last_routine_at: string | null; since: { new_in: number; new_decided: number };
  in: RoutineCol & { n_total: number; n_7d: number; signal_7d: number };
  decided: RoutineCol & { total: number; right: number; unknown: number; partial: number; wrong: number; none: number };
  writing: { drafts: number; cards: RoutineCard[] };
};
export type RoutineRef = { kind: string; id: string; title: string | null; date: string | null;
  author?: string | null; channel?: string | null; ai_summary?: string | null; ai?: boolean;
  item?: { object_key: string; item_id: string; title: string | null; verdict: string | null } | null };
export type RoutineSubhead = { item_id: string; order: number | null; text: string; body: string | null; sources: RoutineRef[] };
export type RoutineDetail = {
  board: { item_id: string; title: string; key_line: string | null; stage: string | null; date: string | null };
  subheads: RoutineSubhead[]; inflow: RoutineRef[]; decided: RoutineRef[]; missing_sources: number;
};
