// 서버 접점 — 같은 origin 의 /api/* 만 부른다. 옛 app.html getJSON·corePost 와 같은 규칙:
// 401 = 시작 화면(/)으로 보낸다 · 연결 실패 = code "OFFLINE" · 그 밖 실패 = 서버 오류 {code, msg, action}.
export type ApiError = { code: string; msg: string; action?: string; status?: number; j?: Record<string, unknown> };   // status = HTTP 상태(연결 실패면 없음) · j = 오류 응답 전체(이관 detail·resume_at)

export class ApiFail extends Error {
  readonly err: ApiError;
  constructor(err: ApiError) {
    super(err.code);
    this.err = err;
  }
}

async function call<T>(url: string, init: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch {
    throw new ApiFail({ code: "OFFLINE", msg: "" });
  }
  if (r.status === 401) {
    location.href = "/";
    throw new ApiFail({ code: "UNAUTHORIZED", msg: "" });
  }
  const j: unknown = await r.json().catch(() => ({}));
  if (r.ok) return j as T;
  const e = (j && typeof j === "object" ? j : {}) as Partial<ApiError>;
  throw new ApiFail({ code: String(e.code || ""), msg: String(e.msg || ""), action: e.action, status: r.status, j: e as Record<string, unknown> });
}

export const apiErr = (e: unknown): ApiError =>
  e instanceof ApiFail ? e.err : { code: "", msg: "" };

export const getJSON = <T>(url: string) => call<T>(url, { cache: "no-store" });

// signal = 시간 제한(응답을 못 받으면 연결 실패와 같게 OFFLINE)
export const postJSON = <T>(url: string, body: unknown, signal?: AbortSignal) =>
  call<T>(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal });
