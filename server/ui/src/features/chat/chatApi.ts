// 대화 서버 접점 — 작업·쌓기 API 는 여기서만 부른다(쓰기 = 작업 접수 · 제외 · 확정 3, 읽기 = 작업 롱폴 · 세션 복원 2).
// 결과 꼴은 옛 app.html stackPost·getJSON 그대로: {ok:true, j} · {ok:false, status, code, msg}(연결 실패 = code OFFLINE, status 0) · null(로그인 풀림 — 시작 화면으로 보냄).
// 응답 모양 정본 = server/web.py api_jobs·api_job_get·api_job_confirm·api_stack_exclude·api_stack_session. 견본 대조 = chat.sample.json ↔ test_tools.py.
import { apiErr, getJSON, postJSON } from "../../shared/api";
import type { Job, Preview, Session } from "./types";

export type Res<T> = { ok: true; j: T } | { ok: false; status: number; code: string; msg: string } | null;

async function wrap<T>(p: Promise<T>): Promise<Res<T>> {
  try {
    return { ok: true, j: await p };
  } catch (e) {
    const er = apiErr(e);
    if (er.code === "UNAUTHORIZED") return null;
    return { ok: false, status: er.status || 0, code: er.code || (er.status ? "" : "OFFLINE"), msg: er.msg || "" };
  }
}

const enc = encodeURIComponent;
export const chatApi = {
  send: (body: object) => wrap(postJSON<{ id: string; session_id: string }>("/api/jobs", body)),
  poll: (jid: string) => wrap(getJSON<Job>(`/api/jobs/${enc(jid)}?wait=30`)),
  exclude: (pid: string, cids: string[]) => wrap(postJSON<{ preview?: Preview } & Partial<Preview>>(`/api/stack/previews/${enc(pid)}/exclude`, { cids })),
  confirm: (jid: string, body: object) => wrap(postJSON<object>(`/api/jobs/${enc(jid)}/confirm`, body)),
  session: (sid: string) => wrap(getJSON<Session>(`/api/stack/sessions/${enc(sid)}`)),
};
export type ChatApi = typeof chatApi;
