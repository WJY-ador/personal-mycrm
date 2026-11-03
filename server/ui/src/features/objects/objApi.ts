// 자료 종류(사람·출처·읽고 든 생각) 서버 접점 — 읽기(문맥 API) + 쓰기(옛 coreSubmit·coreAct 의 경로 그대로). 응답 모양 정본 = server/web.py·db.py.
// 견본 대조 = objects.sample.json(사람·출처 문맥) ↔ server/test_web_import.py test_ui_samples · TS = objects.sample.test.ts(satisfies).
import { getJSON, postJSON } from "../../shared/api";
import type { Act } from "../../shared/activity";

export type PersonCtx = {
  person: { id: string; alias: string; revision: number; linked: boolean };
  activities: Act[]; activity_count: number; old_revision_links: number;
  records: { id: string; title: string | null; created: string }[];
  items: { id: string; object_id: string; title: string | null; field_key: string | null }[];
};
export type SourceCtx = {
  source: { id: string; kind: string; name: string; location: string; provider: string | null };
  activity_count: number; by_action: { action: string; label: string; n: number }[]; activities: Act[] };

const enc = encodeURIComponent;
export const objApi = {
  person: (id: string) => getJSON<PersonCtx>(`/api/people/${enc(id)}/context`),
  source: (id: string) => getJSON<SourceCtx>(`/api/sources/${enc(id)}/context`),
  personNew: (alias: string) => postJSON("/api/people", { alias }),
  personEdit: (id: string, alias: string, expected_revision: number) => postJSON(`/api/people/${enc(id)}`, { alias, expected_revision }),
  personDel: (id: string, expected_revision: number) => postJSON(`/api/people/${enc(id)}/delete`, { expected_revision }),
  sourceNew: (body: { kind: string; name: string; location: string }) => postJSON<{ id?: string }>("/api/sources", body),
  reflNew: (body: { source_id: string; kind: string; body: string }) => postJSON("/api/reflections", body),
  reflEdit: (id: string, body: { source_id: string; kind: string; body: string; expected_revision: number }) =>
    postJSON<{ review?: string }>(`/api/reflections/${enc(id)}`, body),
  reflReview: (id: string, reviewed: boolean, expected_revision: number) => postJSON(`/api/reflections/${enc(id)}/review`, { reviewed, expected_revision }),
  reflDel: (id: string, expected_revision: number) => postJSON(`/api/reflections/${enc(id)}/delete`, { expected_revision }),
  trash: (kind: string, id: string, expected_revision: number) => postJSON("/api/trash/move", { kind, id, expected_revision }),
};
