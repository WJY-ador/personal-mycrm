// 웹 「대화」 서버 접점 — /api/chat/* (server/webchat.py 계약). 출력은 SSE(EventSource) — 브라우저가 끊기면 Last-Event-ID 로 이어 받는다.
import { getJSON, postJSON } from "../../shared/api";

export type Capability = { provider: "claude" | "codex" | "fake"; models: Array<string | null> };
export type DeviceCapability = { device_id: string; connected: boolean; agent_version: string; capabilities_version: number; capabilities: Capability[] };
export type Capabilities = { devices: DeviceCapability[] };
export type Session = { session_id: string; status: string; device_id: string; connected?: boolean; provider: string | null; model: string | null; binding_version: number; created_at?: string; last_at?: string };
export type SessionList = { sessions: Session[] };
// PC 허용(grant) — POST 로 요청, GET 으로 상태를 읽는다(세션이 아직 없어 SSE 대신 1~2초 간격 조회). prompt = PC 동의 창: none 아직, open 떠 있음, done 서명됨, closed 승인 없이 끝남, declined PC 앱이 허용하지 않음을 알림
export type GrantState = "pending" | "approved" | "consumed" | "expired";
export type Grant = { request_id: string; device_id: string; provider: string; model: string | null; state: GrantState; prompt: "none" | "open" | "done" | "closed" | "declined"; expires_at: string; connected?: boolean; created?: boolean };
export type Message = { id: string; turn_id: string; role: "user" | "assistant"; body: string; created_at: string; turn_status: string };
export type TurnRes = { turn_id: string; status: string; created: boolean };
export type Approval = { id: string; turn_id: string; op: string; params: unknown; shown: unknown; impact: unknown; irreversible: boolean; status: "pending" | "confirmed" | "cancelled"; created_at: string; expires_at: string; finished_at: string | null; result: Record<string, unknown> | null };
export type ApprovalList = { approvals: Approval[] };
export type ApprovalAction = { status: "confirmed" | "cancelled"; result?: Record<string, unknown> };
export type Es = { onmessage: unknown; onerror: ((e: unknown) => void) | null; addEventListener: (t: string, f: (e: MessageEvent) => void) => void; close: () => void };

export const webchatApi = {
  sessions: () => getJSON<SessionList>("/api/chat/sessions"),
  capabilities: () => getJSON<Capabilities>("/api/chat/capabilities"),
  resume: (session_id: string) => postJSON<Session>("/api/chat/sessions", { operation: "resume", session_id }),
  create: (device_id: string, provider: string, model: string | null, client_session_id: string) =>
    postJSON<Session>("/api/chat/sessions", { operation: "new", device_id, provider, model, client_session_id }),
  grant: (device_id: string, provider: string, model: string | null, request_id: string) => postJSON<Grant>("/api/chat/grants", { device_id, provider, model, request_id }),
  grantStatus: (request_id: string) => getJSON<Grant>(`/api/chat/grants/${encodeURIComponent(request_id)}`),
  messages: (sid: string) => getJSON<{ messages: Message[] }>(`/api/chat/sessions/${encodeURIComponent(sid)}/messages`),
  turn: (sid: string, text: string, client_turn_id: string) => postJSON<TurnRes>(`/api/chat/sessions/${encodeURIComponent(sid)}/turns`, { text, client_turn_id }),
  stop: (sid: string) => postJSON<{ turn_id: string | null }>(`/api/chat/sessions/${encodeURIComponent(sid)}/stop`, {}),
  approvals: (sid: string) => getJSON<ApprovalList>(`/api/chat/sessions/${encodeURIComponent(sid)}/approvals`),
  confirmApproval: (sid: string, id: string) => postJSON<ApprovalAction>(`/api/chat/sessions/${encodeURIComponent(sid)}/approvals/${encodeURIComponent(id)}/confirm`, {}),
  cancelApproval: (sid: string, id: string) => postJSON<ApprovalAction>(`/api/chat/sessions/${encodeURIComponent(sid)}/approvals/${encodeURIComponent(id)}/cancel`, {}),
  stream: (sid: string): Es => new EventSource(`/api/chat/sessions/${encodeURIComponent(sid)}/stream`) as unknown as Es,
};
export type WebchatApi = typeof webchatApi;
