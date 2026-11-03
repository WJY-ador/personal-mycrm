// 상태 한 벌(/api/state)을 받는 곳 하나 — react-query. 로그인이 풀렸으면 시작 화면(/)으로 보낸다(null).
// reload = 모든 서버 조회를 무효화해 다시 받는다(상태 + 지금 떠 있는 화면의 목록) — 끝나면 상태를 받았는지(true/false)
import { useQuery } from "@tanstack/react-query";
import { queryClient } from "../shared/queries";
import type { AppState } from "../shared/state";

export const STATE_KEY = ["state"];

async function fetchState(): Promise<AppState | null> {
  const r = await fetch("/api/state", { cache: "no-store" });
  if (r.status === 401) { location.href = "/"; return null; }
  return r.json() as Promise<AppState>;
}

export async function reload(): Promise<boolean> {
  await queryClient.invalidateQueries();
  const st = queryClient.getQueryState<AppState | null>(STATE_KEY);
  return st?.status === "success" && !!st.data;
}

// failed = 마지막 받기가 실패(연결 실패 등) — 받아 둔 상태가 있으면 그 화면을 그대로 두고 띠만 건다
export function useAppState() {
  const q = useQuery({ queryKey: STATE_KEY, queryFn: fetchState });
  return { S: q.data || null, failed: q.isError };
}
