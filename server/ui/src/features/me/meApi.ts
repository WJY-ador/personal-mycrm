// 「나」 서버 접점 — 읽기(통계·레이아웃·기록 본문·이어 받기·문맥) + 쓰기(기존 경로 + 수기 수정). 응답 모양 정본 = server/web.py·db.py.
// 견본 대조 = me.sample.json(stats·layout·journal) ↔ server/test_web_home.py test_me_samples.
import { getJSON, postJSON } from "../../shared/api";
import { candidateDecide, fetchJournal, type CandDecide } from "../../shared/journal";
import type { Act } from "../../shared/activity";
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

const enc = encodeURIComponent;
export const meApi = {
  stats: () => getJSON<Stats>("/api/me/stats"),
  layout: () => getJSON<Layout>("/api/me/layout"),
  journal: fetchJournal,
  records: (before: string) => getJSON<{ records: Rec[]; next_before: string | null }>(`/api/records?before=${enc(before)}&limit=50`),
  person: (id: string) => getJSON<PersonCtx>(`/api/people/${enc(id)}/context`),
  axis: (id: string) => getJSON<AxisCtx>(`/api/axes/${enc(id)}/context`),
  source: (id: string) => getJSON<SourceCtx>(`/api/sources/${enc(id)}/context`),
  activity: (id: string) => getJSON<Act>(`/api/activities/${enc(id)}`),
  // 쓰기 — 기존 경로
  name: (display_name: string) => postJSON("/api/me/name", { display_name }),
  reflection: (id: string, body: object) => postJSON(`/api/reflections/${enc(id)}`, body),
  review: (id: string, reviewed: boolean, expected_revision: number) => postJSON(`/api/reflections/${enc(id)}/review`, { reviewed, expected_revision }),
  candidate: (body: CandDecide) => candidateDecide(body),
  itemDecide: (body: object) => postJSON("/api/item/decide", body),
  trash: (kind: string, id: string, rev: number | null) =>
    postJSON("/api/trash/move", rev == null ? { kind, id } : { kind, id, expected_revision: rev }),
  // 쓰기 — 수기 수정(A0′, R2)
  recordTitle: (id: string, expected_revision: number, title: string) => postJSON(`/api/records/${enc(id)}/title`, { expected_revision, title }),
  recordBody: (id: string, expected_revision: number, body: string) => postJSON(`/api/records/${enc(id)}/body`, { expected_revision, body }),
  // 본문 저장 전 미리보기(쓰기 없음, 저장과 같은 판정) — msg = 지워질 검토할 판단이 있을 때만 서버 문구(없으면 "")
  recordBodyPreview: (id: string, expected_revision: number, body: string) =>
    postJSON<BodyPreview>(`/api/records/${enc(id)}/body/preview`, { expected_revision, body }),
  itemEdit: (item_id: string, expected_revision: number, title: string, body: string) =>
    postJSON("/api/item/edit", { item_id, expected_revision, title, body }),
};
