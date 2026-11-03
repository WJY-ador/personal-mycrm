// 「오늘」·저장 승인 대기 서버 접점 — 읽기(대기 목록·하나 · 최근 활동 50) + 쓰기(승인·제외, 옛 coreAct 경로 그대로). 응답 모양 정본 = server/imports.py inbox_*.
// 견본 대조 = today.sample.json ↔ server/test_web_import.py test_ui_samples · TS = today.sample.test.ts(satisfies).
import { getJSON, postJSON } from "../../shared/api";
import type { Act } from "../../shared/activity";

export type Gen = { method?: string; tool?: string; model?: string; input_scope?: string; inputs?: number };
export type Entry = {
  id: string; kind: string; state: string; title: string | null; received_at: string; expires_at: string | null;
  device: { id: string; label: string } | null; execution: string; source_created_at: string | null; source_date: string | null;
  generation: Gen | null; activity_ref: string | null; is_latest: boolean; approvable: boolean; payload_bytes: number;
  resolved_at: string | null; resolved_by: string | null; target_record_id: string | null;
};
export type EntryOne = Entry & { body: string | null; approve_notice: string | null };
export type InboxList = { entries: Entry[]; next_cursor: string; counts: { pending: number } };

const enc = encodeURIComponent;
export const todayApi = {
  list: (state: string, cursor = "") => getJSON<InboxList>(`/api/inbox?state=${enc(state)}${cursor ? `&cursor=${enc(cursor)}` : ""}`),
  acts: () => getJSON<{ activities: Act[]; next_cursor: string }>("/api/activities?limit=50"),
  one: (id: string) => getJSON<EntryOne>(`/api/inbox/${enc(id)}`),
  approve: (id: string) => postJSON(`/api/inbox/${enc(id)}/approve`, {}),
  exclude: (id: string) => postJSON(`/api/inbox/${enc(id)}/exclude`, {}),
};
