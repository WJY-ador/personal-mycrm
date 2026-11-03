// 활동 화면 서버 접점(읽기 + 휴지통 이동). 응답 모양 정본 = server/activity.py·web.py — 견본 activity.sample.json 을
// 서버 시험(test_web_import.py test_ui_samples)이 실제 응답과 대조하고, TS 는 satisfies(activity.sample.test.ts)로 묶는다.
import { getJSON, postJSON } from "../../shared/api";
import type { Act, Agg } from "../../shared/activity";

export type ActList = { activities: Act[]; next_cursor: string };
export type ActOne = Act & {
  raw_id: string | null; current: boolean; current_id: string | null;
  versions: { id: string; received_at: string; state: string; current: boolean }[];
  memos: { record_id: string; title: string | null; created: string }[];
  raw: { raw_id: string; local_only: boolean } | null;
};
export type AxisCtx = {
  axis: { id: string; title: string | null }; activity_count: number; activities: Act[];
  records: { id: string; title: string | null; created?: string }[];
  items: { id: string; object_id: string; title: string | null; field_key: string | null }[];
};

const enc = encodeURIComponent;
export const actApi = {
  list: (qs: string, cursor: string) => {
    const q = new URLSearchParams(qs);
    if (cursor) q.set("cursor", cursor);
    return getJSON<ActList>("/api/activities" + (q.toString() ? "?" + q.toString() : ""));
  },
  one: (id: string) => getJSON<ActOne>(`/api/activities/${enc(id)}`),
  agg: (period: string) => getJSON<Agg>(`/api/me/aggregate?period=${enc(period)}`),
  axis: (id: string) => getJSON<AxisCtx>(`/api/axes/${enc(id)}/context`),
  trash: (id: string) => postJSON("/api/trash/move", { kind: "activity", id }),   // 이 원천의 모든 판을 함께(서버 계약)
};
