// 대화 서버 접점 — 쌓기 API 는 여기서만 부른다(제외 · 세션 복원). 작업 API(접수 · 롱폴 · 확정)는 shared/jobsApi 한 곳에 두고 여기서 결과 꼴만 씌운다.
// 결과 꼴은 옛 app.html stackPost·getJSON 그대로: {ok:true, j} · {ok:false, status, code, msg}(연결 실패 = code OFFLINE, status 0) · null(로그인 풀림 — 시작 화면으로 보냄).
// 응답 모양 정본 = server/web.py api_jobs·api_job_get·api_job_confirm·api_stack_exclude·api_stack_session. 견본 대조 = chat.sample.json ↔ test_tools.py.
import { apiErr, getJSON, postJSON } from "../../shared/api";
import { jobsApi } from "../../shared/jobsApi";
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
  send: (body: object) => wrap(jobsApi.send(body)),
  poll: (jid: string) => wrap(jobsApi.poll<Job>(jid)),
  exclude: (pid: string, cids: string[]) => wrap(postJSON<{ preview?: Preview } & Partial<Preview>>(`/api/stack/previews/${enc(pid)}/exclude`, { cids })),
  confirm: (jid: string, body: object) => wrap(jobsApi.confirm(jid, body)),
  session: (sid: string) => wrap(getJSON<Session>(`/api/stack/sessions/${enc(sid)}`)),
};
export type ChatApi = typeof chatApi;
