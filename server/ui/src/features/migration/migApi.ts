// 이관 서버 접점(웹 세션 경로) — 토큰 · plan 목록 · 확인 · 기준 체크 · 반영 · 취소 · 영수증. 응답 모양 정본 = server/migration.py·web.py.
// 견본 migration.sample.json 을 서버 시험(test_migration_screen.py)이 실제 응답과 대조하고, TS 는 satisfies 로 묶는다.
// 발급 응답의 토큰 원문·항목 본문(payload)은 부르는 쪽 useState 에만 둔다(react-query 캐시·useMutation 금지 — 떠나면 지운다).
import { getJSON, postJSON } from "../../shared/api";

type Tally = Record<string, number>;
export type Counts = { actions: Tally; units: Record<string, Tally> };
export type Tok = { id: string; label: string; created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null; active: boolean };
export type Tokens = { tokens: Tok[]; enabled: boolean; allowed: boolean; token_days: number };
export type Limits = { daily: number; used_today: number; plan_items: number; plan_days: number; open_plans: number };
export type Plan = {
  plan_id: string; source_instance: string; state: string; item_count: number; plan_hash: string | null; via: string | null;
  created_at: string; expires_at: string; applied_at: string | null; closed_at: string | null;
  summary: { dry_run?: Counts } | null;
};
export type Plans = { plans: Plan[]; enabled: boolean; allowed: boolean; limits: Limits };
export type PItem = {
  seq: number; unit_kind: string; action: string; reason: string | null; title: string | null;
  needs_check: boolean; checked: boolean; result: string | null; target_id: string | null;
};
export type Detail = Plan & { counts: Counts; items: PItem[] };
export type Payload = Record<string, unknown> & {
  unit_kind?: string; title?: string; body?: string; author_kind?: string; text_process?: string; generation_kind?: string; sensitivity?: string;
  primary_date?: { kind: string; value: string } | null; review?: { state: string }; source?: { name: string; kind: string; location: string };
};
export type ItemBody = { seq: number; payload: Payload | null };
export type RItem = {
  seq: number; unit_kind: string; result: string; target_id: string | null; stored_hash: string | null; content_hash: string;
  target_state: string | null; original_id: string;
};
export type Receipt = {
  plan_id: string; import_batch_id: string; plan_hash: string; receipt_hash: string; applied_at: string;
  counts: { results: Tally; units: Record<string, Tally> }; items: RItem[];
};

const enc = encodeURIComponent;
const at = (pid: string, op = "") => `/api/migrations/${enc(pid)}${op ? "/" + op : ""}`;
export const migApi = {
  tokens: () => getJSON<Tokens>("/api/migration-tokens"),
  plans: () => getJSON<Plans>("/api/migrations"),
  plan: (pid: string) => getJSON<Detail>(at(pid)),
  receipt: (pid: string) => getJSON<Receipt>(at(pid, "receipt")),
  item: (pid: string, seq: number) => getJSON<ItemBody>(at(pid, "items/" + seq)),
  tokNew: () => postJSON<{ token: string; info?: { label?: string } }>("/api/migration-tokens", {}),
  tokRevoke: (id: string) => postJSON(`/api/migration-tokens/${enc(id)}/revoke`, {}),
  check: (pid: string, seq: number, checked: boolean) => postJSON<Detail>(at(pid, "check"), { seqs: [seq], checked }),   // 한 번에 하나(일괄 체크 없음)
  apply: (pid: string, plan_hash: string) => postJSON<{ already_applied?: boolean }>(at(pid, "apply"), { plan_hash }),
  cancel: (pid: string) => postJSON(at(pid, "cancel"), {}),
};
