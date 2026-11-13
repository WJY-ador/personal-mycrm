// 문의 서버 접점 — 본인 것만(GET /api/feedback · /api/feedback/<id>) + 보내기(POST /api/feedback). 운영자 처리는 /admin/tickets(서버 렌더).
// 응답 모양 정본 = server/web.py api_feedback·db.tickets_mine·ticket_get_mine. 견본 대조 = desk.sample.json ↔ server/test_web_home.py test_ui_samples
import { getJSON, postJSON } from "../../shared/api";

export type Ticket = { id: string; kind: string; text: string; status: string; via: string; created: string; updated: string;
  has_reply: boolean; reply_at: string | null; public_updated: string | null } & Auto;
// 오류 자동 Case(via auto, 2026-11-13) — 같은 오류의 하루 묶음 횟수와 첫, 마지막 시각. 사람이 쓴 문의는 셋 다 null
export type Auto = { auto_count: number | null; auto_first: string | null; auto_last: string | null };
export type TicketHist = { kind: string; from_val: string | null; to_val: string | null; at: string };
export type TicketOne = { id: string; kind: string; text: string; status: string; via: string; created: string; updated: string; reply: string | null;
  reply_at: string | null; public_updated: string | null; history: TicketHist[] } & Auto;

export const DESK_KEY = ["desk", "mine"];
export const deskApi = {
  list: () => getJSON<{ tickets: Ticket[] }>("/api/feedback"),
  one: (id: string) => getJSON<TicketOne>("/api/feedback/" + encodeURIComponent(id)),
  send: (kind: string, text: string, page: string) => postJSON("/api/feedback", { kind, text, page }),
};
