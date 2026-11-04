// 웹 「대화」 서버 접점 — /api/chat/* (server/webchat.py 계약). 출력은 SSE(EventSource) — 브라우저가 끊기면 Last-Event-ID 로 이어 받는다.
import { postJSON } from "../../shared/api";

export type Session = { session_id: string; status: string; device_id: string; connected?: boolean };
export type TurnRes = { turn_id: string; status: string; created: boolean };
export type Es = { onmessage: unknown; onerror: ((e: unknown) => void) | null; addEventListener: (t: string, f: (e: MessageEvent) => void) => void; close: () => void };

export const webchatApi = {
  open: () => postJSON<Session>("/api/chat/sessions", {}),
  turn: (sid: string, text: string, client_turn_id: string) => postJSON<TurnRes>(`/api/chat/sessions/${encodeURIComponent(sid)}/turns`, { text, client_turn_id }),
  stop: (sid: string) => postJSON<{ turn_id: string | null }>(`/api/chat/sessions/${encodeURIComponent(sid)}/stop`, {}),
  stream: (sid: string): Es => new EventSource(`/api/chat/sessions/${encodeURIComponent(sid)}/stream`) as unknown as Es,
};
export type WebchatApi = typeof webchatApi;
