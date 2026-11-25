// 작업 API 서버 접점 — /api/jobs 는 여기서만 부른다(작업 접수 · 작업 롱폴 · 확정). 대화(features/chat/chatApi)와 수집 글 긴 요약(features/today/collectedApi)이 같이 쓴다.
// 결과 꼴은 shared/api 그대로: 성공 = 응답 본문, 실패 = ApiFail 던짐(code NO-DEVICE, RATE-LIMIT, OFFLINE 등). 대화 쪽 {ok, j} 꼴은 chatApi 의 wrap 이 만든다.
// 응답 모양 정본 = server/web.py api_jobs · api_job_get · api_job_confirm, 작업 하나 = server/db.py _job_out. 작업 모양 타입은 부르는 쪽이 정한다(T).
import { getJSON, postJSON } from "./api";

const enc = encodeURIComponent;
export const jobsApi = {
  send: (body: object) => postJSON<{ id: string; session_id: string }>("/api/jobs", body),
  poll: <T>(jid: string) => getJSON<T>(`/api/jobs/${enc(jid)}?wait=30`),
  confirm: (jid: string, body: object) => postJSON<object>(`/api/jobs/${enc(jid)}/confirm`, body),
};
