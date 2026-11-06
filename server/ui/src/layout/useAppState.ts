// 상태 한 벌(/api/state)을 받는 곳 하나 — react-query. 로그인이 풀렸으면 시작 화면(/)으로 보낸다(null).
// reload = 모든 서버 조회를 무효화해 다시 받는다(상태 + 지금 떠 있는 화면의 목록) — 끝나면 상태를 받았는지(true/false)
import { useCallback, useEffect, useRef, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { queryClient } from "../shared/queries";
import type { AppState } from "../shared/state";

export const STATE_KEY = ["state"];
export const AUTO_REFRESH_INTERVAL_MS = 30_000;

export const REVISION_URL = "/api/state/revision";

// 상태 응답(/api/state)의 revision = 서버가 상태를 만들기 전에 잰 값. 정수가 아니면 기준값 없음(null).
export function stateRevision(s: unknown): number | null {
  const r = s && typeof s === "object" ? (s as { revision?: unknown }).revision : undefined;
  return Number.isInteger(r) ? r as number : null;
}

type Marker = { kind: "ok"; revision: number } | { kind: "unauthorized" } | { kind: "soft" };

// 표지 조회 — 200 { revision: 정수 } 만 값. 401 = 로그인 풀림. 그 밖(연결 실패·다른 상태·형식 이상) = 다음 tick에 다시 묻는다.
async function fetchMarker(signal: AbortSignal): Promise<Marker> {
  try {
    const r = await fetch(REVISION_URL, { cache: "no-store", signal: AbortSignal.any([signal, AbortSignal.timeout(15_000)]) });
    if (r.status === 401) return { kind: "unauthorized" };
    if (r.status !== 200) return { kind: "soft" };
    const body: unknown = await r.json();
    const revision = body && typeof body === "object" ? (body as { revision?: unknown }).revision : undefined;
    return Number.isInteger(revision) ? { kind: "ok", revision: revision as number } : { kind: "soft" };
  } catch {
    return { kind: "soft" };
  }
}

export type AutoRefreshOptions = { intervalMs?: number; onUnauthorized?: () => void };

// revision 기반 자동 갱신. 기준값 = 이 훅이 받은 상태 응답의 revision(훅마다 따로 — 표지 응답으로 기준값을 만들지 않는다).
// 30초 tick·탭이 보이게 될 때 표지만 묻는다. 표지 = 기준값이면 아무것도 다시 받지 않는다.
// 다르면 활성 조회만 무효화한다. 편집 중이거나 이미 진행 중인 조회가 있으면 보류했다가, 편집이 끝나거나 QueryCache가 한가해질 때 한 번 처리한다.
// 진행 중인 사용자 조회는 취소하지 않는다(cancelRefetch: false). 다시 받기가 실패하면 보류를 유지하고 다음 tick에 재시도한다.
// 탭이 숨은 동안 표지 응답이 도착해도 다시 받지 않는다 — 보류를 유지하고, 다시 보일 때 표지를 다시 물은 뒤 한 번 처리한다.
export function useAutoRefresh(enabled: boolean, dirty: RefObject<string | null>, revision: number | null, options: AutoRefreshOptions = {}) {
  const { intervalMs = AUTO_REFRESH_INTERVAL_MS, onUnauthorized } = options;
  const baseline = useRef(revision);
  baseline.current = revision;
  const pending = useRef(false), retry = useRef(false), flushing = useRef(false), asking = useRef(false), stopped = useRef(false);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  const flush = useCallback(() => {
    // 숨은 탭 = 다시 받지 않고 보류만 유지한다. 다시 보일 때 표지를 다시 물은 뒤 처리한다.
    if (!pending.current || flushing.current || dirty.current || document.visibilityState !== "visible") return;
    if (queryClient.isFetching() > 0) return; // QueryCache가 한가해질 때 구독이 다시 부른다
    pending.current = false;
    flushing.current = true;
    const startedAt = Date.now();
    void queryClient.invalidateQueries({ type: "active" }, { cancelRefetch: false }).catch(() => undefined).then(() => {
      flushing.current = false;
      const failed = queryClient.getQueryCache().findAll({ type: "active" })
        .some(q => q.state.status === "error" && q.state.errorUpdatedAt >= startedAt);
      // 실패 = 다음 tick에 다시 받는다. 성공 데이터는 React Query 캐시에 그대로 남는다.
      if (failed) retry.current = true;
    });
  }, [dirty]);

  const check = useCallback(async (signal: AbortSignal) => {
    if (!enabled || stopped.current || asking.current || document.visibilityState !== "visible") return;
    asking.current = true;
    let marker: Marker;
    try { marker = await fetchMarker(signal); } finally { asking.current = false; }
    if (signal.aborted) return;
    if (marker.kind === "unauthorized") {
      stopped.current = true;
      (unauthorized.current || (() => { location.href = "/"; }))();
      return;
    }
    if (marker.kind === "soft") return;
    const base = baseline.current;
    if (base === null) return; // 기준값이 없으면 비교하지 않는다
    if (marker.revision !== base || retry.current) {
      retry.current = false;
      pending.current = true;
    }
    // 숨은 동안 보류된 다시 받기는 그사이 수동 새로 고침으로 기준값이 표지와 같아졌어도 보이는 탭에서 한 번 처리한다.
    if (pending.current) flush();
  }, [enabled, flush]);

  const dirtyChanged = useCallback((isDirty: boolean) => {
    // 진행 중인 사용자 조회/더 보기를 편집 진입만으로 취소하지 않는다.
    if (!isDirty) flush();
  }, [flush]);

  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    const tick = () => { void check(ctrl.signal); };
    const timer = window.setInterval(tick, intervalMs);
    const visibility = () => { if (document.visibilityState === "visible") tick(); };
    document.addEventListener("visibilitychange", visibility);
    const stopCache = queryClient.getQueryCache().subscribe(() => {
      if (pending.current) queueMicrotask(flush);
    });
    return () => {
      ctrl.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visibility);
      stopCache();
    };
  }, [enabled, intervalMs, check, flush]);

  return dirtyChanged;
}

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
// revision = 받아 둔 상태 응답의 revision(자동 갱신 기준값) — 없으면 null
export function useAppState() {
  const q = useQuery({ queryKey: STATE_KEY, queryFn: fetchState });
  const S = q.data || null;
  return { S, failed: q.isError, revision: stateRevision(S) };
}
