// 기록 본문 한 편(/api/journal?id=) · 후보 결정(/api/candidate/decide) — 「나」와 판단 검토가 같이 쓰는 서버 접점(같은 조회 키 = 캐시 하나).
// 응답 모양 정본 = server/web.py api_journal·api_candidate_decide. 견본 대조 = features/me/me.sample.json(journal) ↔ test_web_home.py.
import { getJSON, postJSON } from "./api";

export type Journal = { id: string; title: string; body: string; revision: number; author_kind: string; meta: { created: string; source: string | null; question_id: string | null } };

export const journalKey = (id: string) => ["journal", id];
export const fetchJournal = (id: string) => getJSON<Journal>("/api/journal?id=" + encodeURIComponent(id));

// action = confirm · exclude · edit_confirm(text) — expected_revision 은 화면이 본 후보 revision
export type CandDecide = { candidate_id: string; action: string; expected_revision?: number; text?: string };
export const candidateDecide = (body: CandDecide, signal?: AbortSignal) => postJSON("/api/candidate/decide", body, signal);
