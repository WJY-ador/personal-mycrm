// 주소(hash) 구독 — 라이브러리 없는 라우터. 링크·탭·뒤로 가기 모두 hashchange 로 온다.
// guard 가 true(미저장 보호가 주소를 편집 자리로 되돌림)면 그 변경은 화면에 알리지 않는다. 화면이 바뀌면 맨 위로(1열 목록 위치는 그 화면이 되살린다)
import { useCallback, useSyncExternalStore } from "react";

export function useHash(guard: () => boolean): string {
  const sub = useCallback((cb: () => void) => {
    const f = () => { if (guard()) return; cb(); window.scrollTo?.(0, 0); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, [guard]);
  return useSyncExternalStore(sub, () => location.hash);
}
