// 연결 장치 서버 접점 — 목록·연결·토큰 재발급·연결 해제·허용 규칙. 응답 모양 정본 = server/imports.py device_list·device_connect·…
// 견본 devices.sample.json 을 서버 시험(test_web_import.py test_ui_samples)이 실제 응답과 대조하고, TS 는 satisfies 로 묶는다.
// 연결·재발급 응답의 토큰 원문은 부르는 쪽 useState 에만 둔다(react-query 캐시·useMutation 금지).
import { getJSON, postJSON } from "../../shared/api";

export type Policy = { actions: string[]; transform_versions: string[]; axes: string[] };
export type Device = {
  id: string; label: string; created_at: string; token_expires_at: string | null; last_used_at: string | null;
  revoked_at: string | null; token_revoked_at: string | null; policy: Policy; policy_revision: number; active: boolean;
};
export type Choices = {
  actions: { key: string; label: string }[]; transforms: { key: string; label: string }[];
  axis_object_id: string | null; max_axes: number; token_days: number;
};
export type Devices = { devices: Device[]; active: number; max: number; switches: { imports: boolean }; choices: Choices };
type Tok = { token: string };
// 대화 하나로 J(JD3): PC 의 서 있는 AI 대화 허용 — 조회 GET /api/chat/permits(살아 있는 것만), 해제 POST /api/chat/permits/revoke.
// 웹 대화 스위치가 꺼져 있으면 서버가 503 이라 화면은 허용 줄을 보이지 않는다
export type Permit = { device_id: string; installation_id: string; provider: string; created_at: string };

const enc = encodeURIComponent;
export const devApi = {
  list: () => getJSON<Devices>("/api/devices"),
  connect: (label: string) => postJSON<Tok & { device: { label: string } }>("/api/devices", { label }),
  reissue: (id: string) => postJSON<Tok>(`/api/devices/${enc(id)}/reissue`, {}),
  revoke: (id: string) => postJSON(`/api/devices/${enc(id)}/revoke`, {}),
  policy: (id: string, policy: Policy, expected_revision: number) => postJSON(`/api/devices/${enc(id)}/policy`, { policy, expected_revision }),
  permits: () => getJSON<{ permits: Permit[] }>("/api/chat/permits"),
  revokePermit: (device_id: string, provider: string) => postJSON<{ revoked: number }>("/api/chat/permits/revoke", { device_id, provider }),
};
