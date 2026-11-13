// 수집 인박스 서버 접점 — 읽기(인박스 = pending · 보관함 = kept) + 쓰기(판별 하나 · 묶음 버림). 응답 모양 정본 = server/imports.py collected_*.
// 견본 대조 = collected.sample.json ↔ server/test_collected_inbox.py test_ui_sample · TS = collected.sample.test.ts(satisfies).
import { getJSON, postJSON } from "../../shared/api";

export type Ai = { grade: string | null; summary: string | null; as_is: string | null; to_be: string | null; ops: string | null; points: string[] | null };
export type Post = {
  id: string; revision: number; title: string; channel: string | null; author_display: string | null; post_url: string | null;
  posted_on: string | null; collected_on: string | null; axes: { id: string; title: string }[]; ai: Ai;
  state: string; decided_by: string | null; decided_at: string | null;
};
export type PostList = { ready: boolean; posts: Post[]; counts: { pending: number; kept: number } };
export type Decided = { item_id: string; state: string; revision: number; decided_at: string | null };
export type Dropped = { dropped: string[]; skipped: string[] };

const enc = encodeURIComponent;
export const BULK_MAX = 200;   // 묶음 버림 한 번에(서버 상한과 같다)
export const collectedApi = {
  list: (state: "pending" | "kept") => getJSON<PostList>(`/api/collected?state=${state}`),
  decide: (id: string, state: string, expected_revision: number) => postJSON<Decided>(`/api/collected/${enc(id)}/decide`, { state, expected_revision }),
  drop: (ids: string[]) => postJSON<Dropped>("/api/collected/drop", { ids, state: "dropped" }),
};
