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
