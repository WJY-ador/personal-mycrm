// 대화 응답 조각의 타입(손 사본 — 화면이 읽는 키 + 견본 대조에 쓰는 키). 정본 = server/stack_service.py display · db.py _job_out·job_get·stack_session_get.
// 견본 chat.sample.json 을 서버 시험(test_tools.py test_chat_samples)이 실제 응답과 키·값 타입까지 대조하고, tsc 가 satisfies 로 묶는다.
export type Unit = { uid: string; text: string; change_ids: string[] };
export type Change = {
  cid: string; op: string; object_id: string; object_label: string; summary: string; ref_kind: string; inferred: boolean;
  depends_on: string[]; unit_ids: string[]; label?: string;
};
export type Blocked = { cid: string | null; code: string; question: string };
export type Preview = {
  id: string; job_id: string; session_id: string; preview_version: number; preview_sha: string; edit_generation: number;
  units: Unit[]; text: string; changes: Change[]; blocked: Blocked[]; blocked_open: boolean; excluded: string[];
  excluded_changes: { cid: string; summary: string }[]; latest: boolean;
};
export type Job = {
  id: string; session_id: string; kind: string; status: string; input_version: number; attempts: number; reason_code: string | null;
  created_at: string; expires_at: string; terminal_at: string | null;
  result?: { result_version: string; summary_text: string } | null; preview?: Preview;
};
export type Session = {
  session_id: string; input_kind: string; expires_at: string; edit_generation: number;
  latest_job: { id: string; status: string } | null; preview: Preview | null; confirmed: boolean;
};
export type Excluded = { preview: Preview; removed: string[] };
