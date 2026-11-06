// 상태 한 벌(/api/state)을 받는 곳 하나 — react-query. 로그인이 풀렸으면 시작 화면(/)으로 보낸다(null).
// reload = 모든 서버 조회를 무효화해 다시 받는다(상태 + 지금 떠 있는 화면의 목록) — 끝나면 상태를 받았는지(true/false)
import { useQuery } from "@tanstack/react-query";
import { queryClient } from "../shared/queries";
import type { AppState } from "../shared/state";

export const STATE_KEY = ["state"];

async function fetchState({ signal }: { signal: AbortSignal }): Promise<AppState | null> {
  const timeout = AbortSignal.timeout(15_000);
  const requestSignal = AbortSignal.any([signal, timeout]);
  const r = await new Promise<Response>((resolve, reject) => {
    const onAbort = () => reject(requestSignal.reason || new DOMException("요청 시간이 초과됐어요.", "AbortError"));
    if (requestSignal.aborted) { onAbort(); return; }
    requestSignal.addEventListener("abort", onAbort, { once: true });
    fetch("/api/state", { cache: "no-store", signal: requestSignal }).then(
      response => { requestSignal.removeEventListener("abort", onAbort); resolve(response); },
      error => { requestSignal.removeEventListener("abort", onAbort); reject(error); },
    );
  });
  if (r.status === 401) { location.href = "/"; return null; }
  if (!r.ok) throw new Error(`상태 조회 실패: HTTP ${r.status}`);
  return r.json() as Promise<AppState>;
}

export async function reload(): Promise<boolean> {
  await queryClient.invalidateQueries();
  const st = queryClient.getQueryState<AppState | null>(STATE_KEY);
  return st?.status === "success" && !!st.data;
}

// 수동 새로 고침도 기존처럼 모든 활성 조회를 갱신하지만, 머리글 피드백은 상태 조회만 기다린다.
export function reloadState(): Promise<boolean> {
  void queryClient.invalidateQueries();
  const state = () => queryClient.getQueryState<AppState | null>(STATE_KEY);
  const result = () => {
    const st = state();
    if (st?.fetchStatus === "fetching") return null;
    if (st?.fetchStatus === "paused") return false;
    return st?.status === "success" && !!st.data;
  };
  const current = result();
  if (current !== null) return Promise.resolve(current);
  return new Promise(resolve => {
    const stop = queryClient.getQueryCache().subscribe(() => {
      const currentResult = result();
      if (currentResult !== null) {
        stop();
        resolve(currentResult);
      }
    });
  });
}

// failed = 마지막 받기가 실패(연결 실패 등) — 받아 둔 상태가 있으면 그 화면을 그대로 두고 띠만 건다
export function useAppState() {
  const q = useQuery({ queryKey: STATE_KEY, queryFn: fetchState });
  return { S: q.data || null, failed: q.isError };
}
