// 오류 자동 보고(2026-11-13 명세 1.4) — 화면의 5xx, 알 수 없는 오류, 웹 대화 실패를 운영자 문의(자동 Case)로 보낸다. 사용자는 아무것도 하지 않는다.
// 계약 정본 = server/auto_cases.py: POST /api/error-reports {source web, stage, code, app_version "", os, occurred_at, count}.
// 싣는 것은 단계 코드와 오류 코드뿐이다(주소의 id, 본문, 오류 문장은 싣지 않는다). 같은 (단계, 코드)는 FLUSH_MS 동안 모아 횟수로 한 번 보낸다.
// 보고가 실패해도 다시 보고하지 않는다(재시도 없음, 이 파일은 shared/api 의 call 을 쓰지 않는다 — 되먹임 방지).
const STAGE_RE = /^[a-z][a-z0-9-]{0,23}(?:\/[a-z0-9-]{1,32}){0,2}$/;
const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/;
const FLUSH_MS = 3000;
const PER_PAGE = 50;   // 한 페이지 수명에서 보내는 보고 상한(폭주 방어)

const pending = new Map<string, { stage: string; code: string; n: number }>();
let timer: ReturnType<typeof setTimeout> | null = null;
let sent = 0;

export function osKind(ua = typeof navigator === "undefined" ? "" : navigator.userAgent): "mac" | "win" | "other" {
  return /Mac OS X|Macintosh/.test(ua) ? "mac" : /Windows/.test(ua) ? "win" : "other";
}

// /api/chat/sessions/cs_1/turns → api/chat/sessions — 낱말 꼴(소문자, 하이픈)인 조각만 앞에서 둘까지. id(밑줄, 숫자 섞임)는 버린다
export function stageOf(url: string): string {
  let path = url;
  try { path = new URL(url, "http://x").pathname; } catch { /* 그대로 */ }
  const words = path.split("/").filter(Boolean).slice(1).filter(s => /^[a-z][a-z-]{0,31}$/.test(s)).slice(0, 2);
  return ["api", ...words].join("/");
}

function flush() {
  timer = null;
  const items = [...pending.values()];
  pending.clear();
  for (const it of items) {
    if (sent >= PER_PAGE) return;
    sent++;
    const body = { source: "web", stage: it.stage, code: it.code, app_version: "", os: osKind(),
      occurred_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"), count: Math.min(it.n, 1000) };
    try {
      void fetch("/api/error-reports", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), keepalive: true })
        .catch(() => undefined);
    } catch { /* 보고 실패는 다시 보고하지 않는다 */ }
  }
}

export function reportError(stage: string, code: string) {
  if (!STAGE_RE.test(stage)) return;
  const c = CODE_RE.test(code) ? code : "unknown";
  const key = `${stage}|${c}`;
  const hit = pending.get(key);
  if (hit) hit.n++; else pending.set(key, { stage, code: c, n: 1 });
  if (!timer) timer = setTimeout(flush, FLUSH_MS);
}

// 시험용 — 모은 것을 바로 보내고 상태를 비운다
export function _flushNow() { if (timer) clearTimeout(timer); flush(); sent = 0; }

// 우리 화면 스크립트(같은 출처의 /app/assets/)에서 난 오류인가 — 확장 프로그램, 자동화 도구, 다른 출처 스크립트, ResizeObserver 경고는 빼서
// 사용자 탓이 아닌 잡음 Case 를 만들지 않는다. 문장과 파일 이름은 판정에만 쓰고 보내지 않는다
export function ownError(e: { message?: unknown; filename?: unknown }, origin = typeof location === "undefined" ? "" : location.origin) {
  const msg = typeof e.message === "string" ? e.message : "", file = typeof e.filename === "string" ? e.filename : "";
  return !!origin && file.startsWith(origin + "/app/assets/") && !/ResizeObserver loop/.test(msg);
}

// 화면 전체의 알 수 없는 오류(잡히지 않은 예외, 거절된 약속). 오류 문장은 싣지 않는다. 거절된 약속 중 API 실패(ApiFail)는 call 이 이미 5xx 만 보냈다
export function installGlobalReport(w: Window = window) {
  w.addEventListener("error", e => { if (ownError(e)) reportError("ui/error", "unknown"); });
  w.addEventListener("unhandledrejection", e => {
    const r = (e as PromiseRejectionEvent).reason;
    if (!(r instanceof Error) || "err" in r) return;   // ApiFail(err 필드) = API 실패는 call 이 맡는다(빌드는 이름을 줄여 이름으로 못 가린다)
    if (typeof r.stack === "string" && !r.stack.includes("/app/assets/")) return;
    reportError("ui/promise", "unknown");
  });
}
