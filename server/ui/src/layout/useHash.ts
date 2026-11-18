// 주소(hash) 구독 — 라이브러리 없는 라우터. 링크·탭·뒤로 가기 모두 hashchange 로 온다.
// guard 가 true(미저장 보호가 주소를 편집 자리로 되돌림)면 그 변경은 화면에 알리지 않는다. 화면이 바뀌면 맨 위로(1열 목록 위치는 그 화면이 되살린다)
import { useCallback, useSyncExternalStore } from "react";
import { AI_HASH, hashOf } from "../shared/aiAsk";

// AI 패널 표지(AI_HASH)는 화면 주소가 아니다 — 그 hash 인 동안은 마지막 화면 주소를 그대로 돌려주고, 그 hashchange 는 알리지 않는다
// (웹 대화 섬이 표지를 지우며 앞 주소로 되돌린다. 리스너 순서와 상관없이 사건의 newURL 로 가린다. 미저장 보호, 맨 위로도 건드리지 않는다)
let last = "";
const read = () => (location.hash === AI_HASH ? last : (last = location.hash));

export function useHash(guard: () => boolean): string {
  const sub = useCallback((cb: () => void) => {
    const f = (e: HashChangeEvent) => { if (location.hash === AI_HASH || hashOf(e.newURL) === AI_HASH) return; if (guard()) return; cb(); window.scrollTo?.(0, 0); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, [guard]);
  return useSyncExternalStore(sub, read);
}
