// 시험 도우미 — 가짜 서버 접점을 단 대화 저장소 · 미리보기 견본. 화면 코드가 아니다(*.test 만 import).
import { vi } from "vitest";
import type { AppState } from "../shared/state";
import type { ChatApi } from "../features/chat/chatApi";
import { ChatStore } from "../features/chat/store";
import type { Change, Preview } from "../features/chat/types";

export const NODEV = "이 기능은 본인 PC에서 본인 Claude 구독으로 실행하며, PC 연결과 에이전트 실행이 필요해요.";   // PRD 1-2 고정 문구(글자 그대로, 2026-11-12 디자인 2 C6에서 해요체로)
export const T = "2026-10-22T05:03:00+00:00";

export function mk() {
  const s = new ChatStore();
  s.api = {
    send: vi.fn(async () => ({ ok: true, j: { id: "jx", session_id: "s1" } })),
    poll: vi.fn(() => new Promise(() => {})),   // 롱폴이 돌아오기 전 — 시험이 필요하면 바꾼다
    exclude: vi.fn(async () => null),
    confirm: vi.fn(async () => ({ ok: true, j: {} })),
    session: vi.fn(async () => null),
  } as unknown as ChatApi;
  return s;
}

export const ch = (cid: string, summary: string, x: Partial<Change> = {}): Change =>
  ({ cid, op: "create", object_id: "od_x", object_label: "판단", summary, ref_kind: "new", inferred: false, depends_on: [], unit_ids: [], ...x });

export const pv = (x: Partial<Preview> = {}): Preview => ({
  id: "p1", job_id: "j1", session_id: "s1", preview_version: 1, preview_sha: "h1", edit_generation: 0, text: "", latest: true,
  blocked: [], blocked_open: false, excluded: [], excluded_changes: [],
  units: [{ uid: "u1", text: "하나", change_ids: ["c1"] }, { uid: "u2", text: "둘", change_ids: ["c2"] }],
  changes: [ch("c1", "새 결정: 가"), ch("c2", "새 판단: 나")], ...x,
});

export const st = (x: object = {}) => ({ user: { display_name: "홍길동", nav: "new" }, switches: { trash: false, converse: true }, ...x }) as unknown as AppState;
