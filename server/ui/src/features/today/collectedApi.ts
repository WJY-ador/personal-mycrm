// 수집 인박스 서버 접점 — 읽기(인박스 = pending · 보관함 = kept) + 쓰기(판별 하나 · 묶음 버림). 응답 모양 정본 = server/imports.py collected_*.
// 견본 대조 = collected.sample.json ↔ server/test_collected_inbox.py test_ui_sample · TS = collected.sample.test.ts(satisfies).
import { getJSON, postJSON } from "../../shared/api";

export type Ai = { grade: string | null; summary: string | null; as_is: string | null; to_be: string | null; ops: string | null; points: string[] | null };
export type Post = {
  id: string; revision: number; title: string; channel: string | null; author_display: string | null; post_url: string | null;
  posted_on: string | null; collected_on: string | null; axes: { id: string; code: string | null; title: string }[]; ai: Ai;   // code = 축 코드(축 잇기, 코드 없는 축은 null)
  state: string; decided_by: string | null; decided_at: string | null;
};
export type PostList = { ready: boolean; posts: Post[]; counts: { pending: number; kept: number } };
export type Decided = { item_id: string; state: string; revision: number; decided_at: string | null };
export type Dropped = { dropped: string[]; skipped: string[] };
// 인박스 요약(GET /api/collected/digest, 2026-11-22 구현계획 4-3) — digest = PC 가 만든 AI 요약(없으면 null, 근거 아님) · new_since = 요약 뒤 생긴 대기 수 ·
// by_axis = 축별 대기, 신호 수(모델 없이 서버가 센다)
export type Theme = { name: string; line: string; item_ids: string[] };
export type DigestAxis = { code: string | null; title: string | null; item_id: string; pending: number; signal: number };
export type Digest = { digest: { themes: Theme[]; input_n: number; made_at: string } | null; pending_n: number; new_since: number; by_axis: DigestAxis[] };
// 읽기 판 긴 요약 작업(2026-11-25 구현계획 1절) — POST /api/jobs {kind: "collected_long", text: 항목 id} = 201 {id}(같은 항목의 열린 작업이면 그 작업) ·
// GET /api/jobs/<id>?wait=30 = 상태(queued, leased, running 동안 롱폴). 끝 = confirmed(서버가 항목 ai_* 를 이미 씀) · failed(reason_code) 등. 응답 정본 = server/db.py _job_out
export type LongJob = { id: string; status: string; reason_code: string | null; created_at: string };

const enc = encodeURIComponent;
export const BULK_MAX = 200;   // 묶음 버림 한 번에(서버 상한과 같다)
export const collectedApi = {
  list: (state: "pending" | "kept") => getJSON<PostList>(`/api/collected?state=${state}`),
  decide: (id: string, state: string, expected_revision: number) => postJSON<Decided>(`/api/collected/${enc(id)}/decide`, { state, expected_revision }),
  digest: () => getJSON<Digest>("/api/collected/digest"),
  drop: (ids: string[]) => postJSON<Dropped>("/api/collected/drop", { ids, state: "dropped" }),
  long: (id: string) => postJSON<{ id: string }>("/api/jobs", { kind: "collected_long", text: id }),
  job: (jid: string) => getJSON<LongJob>(`/api/jobs/${enc(jid)}?wait=30`),
};
