// 서버 접점 — 같은 origin 의 /api/* 만 부른다. 옛 app.html getJSON·corePost 와 같은 규칙:
// 401 = 시작 화면(/)으로 보낸다 · 연결 실패 = code "OFFLINE" · 그 밖 실패 = 서버 오류 {code, msg, action}.
export type ApiError = { code: string; msg: string; action?: string };

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
  throw new ApiFail({ code: String(e.code || ""), msg: String(e.msg || ""), action: e.action });
}

export const apiErr = (e: unknown): ApiError =>
  e instanceof ApiFail ? e.err : { code: "", msg: "" };

export const getJSON = <T>(url: string) => call<T>(url, { cache: "no-store" });

export const postJSON = <T>(url: string, body: unknown) =>
  call<T>(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
