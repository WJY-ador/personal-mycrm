// 앱 다리 — 이 PC(window.mycrmDesktop.pc)와 AI 연결(window.mycrmDesktop.ai). 계약 = 2026-11-13 앱 하나 명세 S 계약 (3).
// 규칙은 업데이트 다리(shared/desktopUpdate)와 같다: 값은 get() 으로 읽고, 바뀌면 onChange 가 새 값을 준다. 동작(sync, connect, disconnect)은
// 바로 끝나고 결과는 상태로 온다. 다리가 없으면(브라우저, 0.1.6 이하 앱) null — 화면은 안내 문구를 보인다.
// 값 검사가 틀리면 null(그리지 않는다). 코드 값은 서버 오류 보고와 같은 꼴(영문, 숫자, 밑줄, 하이픈)만 받는다.
const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

export type PcPhase = "ok" | "syncing" | "failed" | "login" | "stopped";
export type PcState = { signedIn: boolean; deviceId: string | null; state: PcPhase; lastSyncAt: string | null; lastResult: "ok" | "failed" | null;
  lastCode: string | null; appVersion: string };
export type AiProvider = "claude" | "codex";
export type AiLinkState = "linked" | "signed_out" | "off" | "missing" | "checking" | "linking";
export type AiState = { providers: { provider: AiProvider; state: AiLinkState; code: string | null }[] };

type Bridge<T> = { get(): Promise<unknown>; onChange(cb: (v: unknown) => void): unknown } & T;
export type PcBridge = Bridge<{ sync(): Promise<void> }>;
export type AiBridge = Bridge<{ connect(p: AiProvider): Promise<void>; disconnect(p: AiProvider): Promise<void> }>;

function pick<T>(w: unknown, name: "pc" | "ai", calls: string[]): T | null {
  try {
    const b = (w as { mycrmDesktop?: Record<string, Record<string, unknown> | undefined> } | undefined)?.mycrmDesktop?.[name];
    if (!b || typeof b !== "object") return null;
    return calls.every(k => typeof b[k] === "function") ? b as unknown as T : null;
  } catch { return null; }
}
const W = () => (typeof window === "undefined" ? undefined : window);
export const pcBridge = (w: unknown = W()) => pick<PcBridge>(w, "pc", ["get", "onChange", "sync"]);
export const aiBridge = (w: unknown = W()) => pick<AiBridge>(w, "ai", ["get", "onChange", "connect", "disconnect"]);

const PHASES: readonly string[] = ["ok", "syncing", "failed", "login", "stopped"];
const LINKS: readonly string[] = ["linked", "signed_out", "off", "missing", "checking", "linking"];
const code = (v: unknown) => (v === null ? null : typeof v === "string" && CODE_RE.test(v) ? v : undefined);

export function parsePc(x: unknown): PcState | null {
  if (!x || typeof x !== "object") return null;
  const s = x as Record<string, unknown>;
  const lastCode = code(s.last_code);
  if (typeof s.signed_in !== "boolean" || typeof s.state !== "string" || !PHASES.includes(s.state)) return null;
  if (s.device_id !== null && (typeof s.device_id !== "string" || s.device_id.length > 200)) return null;
  if (s.last_sync_at !== null && (typeof s.last_sync_at !== "string" || !ISO_RE.test(s.last_sync_at))) return null;
  if (s.last_result !== null && s.last_result !== "ok" && s.last_result !== "failed") return null;
  if (lastCode === undefined || typeof s.app_version !== "string" || s.app_version.length > 40) return null;
  return { signedIn: s.signed_in, deviceId: s.device_id as string | null, state: s.state as PcPhase, lastSyncAt: s.last_sync_at as string | null,
    lastResult: s.last_result as PcState["lastResult"], lastCode, appVersion: s.app_version };
}

export function parseAi(x: unknown): AiState | null {
  if (!x || typeof x !== "object" || !Array.isArray((x as { providers?: unknown }).providers)) return null;
  const out: AiState["providers"] = [];
  for (const p of (x as { providers: unknown[] }).providers) {
    if (!p || typeof p !== "object") return null;
    const { provider, state } = p as Record<string, unknown>;
    const c = code((p as Record<string, unknown>).code ?? null);
    if ((provider !== "claude" && provider !== "codex") || typeof state !== "string" || !LINKS.includes(state) || c === undefined) return null;
    if (out.some(o => o.provider === provider)) return null;
    out.push({ provider, state: state as AiLinkState, code: c });
  }
  return { providers: out };
}

// 다리 호출이 던지거나 거절해도 화면은 그대로 — 결과는 상태(onChange)로 온다
export function quietCall(f: () => unknown): void {
  try { void Promise.resolve(f()).catch(() => {}); } catch { /* 다리 오류 */ }
}
