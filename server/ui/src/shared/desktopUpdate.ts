// PC 앱 새 버전 띠의 판정 — 화면이 대시보드 앱 창(Electron UA)에 떠 있고, 게시된 안정 릴리스가 설치 버전보다 클 때만.
// 설치 버전 = Electron 기본 UA 의 앱 토큰(앱이 UA 를 덮어쓰지 않는다). 최신 = GitHub releases/latest(앱의 업데이트 확인과 같은 출처, publish 뒤에만 참).
// 서버는 관여하지 않는다. 실패·오프라인·형식 이상 = null(띠 없음, 오류 문구 없음).
export const RELEASE_REPO = "WJY-ador/personal-mycrm";
export const LATEST_URL = `https://api.github.com/repos/${RELEASE_REPO}/releases/latest`;
const RELEASE_PAGE = `https://github.com/${RELEASE_REPO}/releases/`;
export const DISMISS_KEY = "mycrm.desktop-update.dismissed";
export const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;   // 오래 켜 둔 앱 — 6시간마다
export const VISIBLE_GAP_MS = 60 * 60 * 1000;       // 창이 다시 보일 때는 마지막 확인에서 1시간이 지났을 때만
export const SNOOZE_MS = 24 * 60 * 60 * 1000;       // 나중에 = 같은 버전은 24시간 뒤 다시

export type Release = { version: string; url: string };   // version = tag_name 그대로(vX.Y.Z)
export type Dismissed = { version: string; at: number };

const VER = /^v?(\d+)\.(\d+)\.(\d+)$/;
const parse = (v: string) => VER.exec(v)?.slice(1).map(Number) ?? null;

// a 가 b 보다 새 버전인가(숫자 비교). 어느 쪽이든 X.Y.Z 꼴이 아니면 false
export function newer(a: string, b: string): boolean {
  const x = parse(a), y = parse(b);
  if (!x || !y) return false;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

// 앱 창의 설치 버전(X.Y.Z) — Electron/ 과 앱 토큰(package.json name 또는 productName)이 둘 다 있을 때만. 없으면 null(띠 없음)
export function installedVersion(ua: string): string | null {
  if (!/(?:^|\s)Electron\/\d/.test(ua)) return null;
  return /(?:^|\s)(?:mycrm-desktop|MyCRM)\/(\d+\.\d+\.\d+)(?=\s|$)/.exec(ua)?.[1] ?? null;
}

// releases/latest 응답 → 안정 릴리스만. draft·prerelease·vX.Y.Z 아닌 태그·이 레포 릴리스 페이지가 아닌 주소는 버린다
export function parseRelease(j: unknown): Release | null {
  if (!j || typeof j !== "object") return null;
  const r = j as { draft?: unknown; prerelease?: unknown; tag_name?: unknown; html_url?: unknown };
  if (r.draft === true || r.prerelease === true) return null;
  if (typeof r.tag_name !== "string" || !/^v\d+\.\d+\.\d+$/.test(r.tag_name)) return null;
  if (typeof r.html_url !== "string") return null;
  try {
    const u = new URL(r.html_url);
    if (u.href !== r.html_url || !u.href.startsWith(RELEASE_PAGE) || u.username || u.password) return null;
  } catch { return null; }
  return { version: r.tag_name, url: r.html_url };
}

export async function fetchLatest(signal?: AbortSignal): Promise<Release | null> {
  try {
    const r = await fetch(LATEST_URL, { cache: "no-store", credentials: "omit", signal });
    return r.ok ? parseRelease(await r.json()) : null;
  } catch { return null; }
}

// 나중에 기록 — 이 브라우저(앱 창 저장소)에만. 못 읽거나 못 쓰면 닫기만 하고 다음 로드에 다시 뜬다
export function readDismissed(): Dismissed | null {
  try {
    const d = JSON.parse(localStorage.getItem(DISMISS_KEY) || "null") as Partial<Dismissed> | null;
    return d && typeof d.version === "string" && typeof d.at === "number" ? { version: d.version, at: d.at } : null;
  } catch { return null; }
}
export function saveDismissed(d: Dismissed): void {
  try { localStorage.setItem(DISMISS_KEY, JSON.stringify(d)); } catch { /* 저장소를 못 쓰는 창 — 이번 화면에서만 닫는다 */ }
}

// 띠를 띄울지 — 새 버전이고, 그 버전을 24시간 안에 나중에 하지 않았을 때. 더 새 버전이면 기록과 상관없이 띄운다
export function shouldShow(installed: string | null, rel: Release | null, dismissed: Dismissed | null, now: number): boolean {
  if (!installed || !rel || !newer(rel.version, installed)) return false;
  return !(dismissed && dismissed.version === rel.version && now >= dismissed.at && now - dismissed.at < SNOOZE_MS);
}

// ── 앱 다리(window.mycrmDesktop.update) — 업데이트 확인은 앱 메인 프로세스 한 곳. 다리가 있으면 띠는 앱이 알려 준 상태만 그린다(GitHub 조회 없음).
// 계약 = 구현계획 0.2.2. 버전은 v 없이(X.Y.Z) 온다. URL 은 받지 않는다 — 릴리스 페이지는 RELEASE_REPO 로 만든다.
export type UpdatePhase = "idle" | "checking" | "available" | "downloading" | "downloaded" | "error";
export type UpdateReason = "network" | "verify" | "install" | "unknown";
export type UpdateState = { inApp: boolean; phase: UpdatePhase; current: string; version: string | null; percent: number | null; reason: UpdateReason | null };
export type DesktopUpdate = {
  get(): Promise<unknown>;
  onChange(cb: (s: unknown) => void): unknown;
  download(): Promise<void>;
  install(): Promise<void>;
};

const PHASES: readonly string[] = ["idle", "checking", "available", "downloading", "downloaded", "error"];
const REASONS: readonly string[] = ["network", "verify", "install", "unknown"];
const BARE = /^\d+\.\d+\.\d+$/;

// 다리가 계약 모양(함수 넷)일 때만 돌려준다. 아니면 null = 옛 앱·일반 브라우저 → 지금 동작(UA 판정, 직접 조회)
export function desktopBridge(w: unknown = typeof window === "undefined" ? undefined : window): DesktopUpdate | null {
  try {
    const u = (w as { mycrmDesktop?: { update?: Record<string, unknown> } } | undefined)?.mycrmDesktop?.update;
    if (!u || typeof u !== "object") return null;
    return ["get", "onChange", "download", "install"].every(k => typeof u[k] === "function") ? u as unknown as DesktopUpdate : null;
  } catch { return null; }
}

// 다리가 준 상태 검사 — 모양이 틀리면 null(띠 없음). 새 버전이 있어야 하는 단계는 설치 버전보다 큰 X.Y.Z 여야 한다.
// inApp=false 는 idle·checking·available 만. percent 는 downloading 에서만 쓰고(null 이면 숫자 없이), reason 은 error 에서만 쓴다(null = unknown)
export function parseState(x: unknown): UpdateState | null {
  if (!x || typeof x !== "object") return null;
  const s = x as Record<string, unknown>;
  const { inApp, phase, current, version, percent, reason } = s;
  if (typeof inApp !== "boolean" || typeof phase !== "string" || !PHASES.includes(phase)) return null;
  if (typeof current !== "string" || !BARE.test(current)) return null;
  if (version !== null && (typeof version !== "string" || !BARE.test(version))) return null;
  if (percent !== null && (typeof percent !== "number" || !Number.isInteger(percent) || percent < 0 || percent > 100)) return null;
  if (reason !== null && (typeof reason !== "string" || !REASONS.includes(reason))) return null;
  if (!inApp && !["idle", "checking", "available"].includes(phase)) return null;
  if (["available", "downloading", "downloaded"].includes(phase) && !(version && newer(version, current))) return null;
  return {
    inApp, phase: phase as UpdatePhase, current, version: version as string | null,
    percent: phase === "downloading" ? percent as number | null : null,
    reason: phase === "error" ? (reason as UpdateReason | null) ?? "unknown" : null,
  };
}

// 릴리스 페이지 — 버전을 알면 그 태그(옛 길과 같은 모양), 모르면 목록. 앱 창은 github.com 링크를 시스템 브라우저로 연다
export function releasePage(version: string | null): string {
  return version && BARE.test(version) ? `${RELEASE_PAGE}tag/v${version}` : `https://github.com/${RELEASE_REPO}/releases`;
}

// 나중에 기록은 옛 길과 같은 꼴(vX.Y.Z)로 저장하고, 비교할 때만 v 를 뗀다 — 옛 기록과 새 값이 어긋나지 않게
const bare = (v: string) => v.replace(/^v/, "");
// 앱 상태로 띠를 띄울지 — idle·checking 은 없음. 나중에는 버튼이 있는 available·downloaded 에만(같은 버전 24시간). downloading·error 는 늘 보인다
export function shouldShowApp(s: UpdateState | null, dismissed: Dismissed | null, now: number): boolean {
  if (!s || s.phase === "idle" || s.phase === "checking") return false;
  if (s.phase === "downloading" || s.phase === "error") return true;
  return !(dismissed && s.version && bare(dismissed.version) === s.version && now >= dismissed.at && now - dismissed.at < SNOOZE_MS);
}
