// 서버 조회 캐시 하나. 다시 받는 때 = 옛 껍데기의 새 상태 알림(crm:state, main.tsx) — 그 밖엔 다시 받지 않는다
// (옛 화면이 상태 한 벌마다 목록을 한 번 받던 것과 같다). 실패는 그대로 보여 주고 자동 재시도하지 않는다.
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false },
  },
});
