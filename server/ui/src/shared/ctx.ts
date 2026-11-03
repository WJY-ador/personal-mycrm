// 옛 껍데기(app.html)가 옮긴 화면에 넘기는 것. reload = 상태 한 벌을 다시 받는다(끝나면 껍데기가 crm:state 를 알린다).
// state = 껍데기가 가진 상태 S(같은 값 — 화면이 /api/state 를 따로 받지 않는다) · args = 주소의 하위 조각(#<탭>/<a>/<b> 의 a·b)
// · setDirty = 고치던 글이 있는 주소(없으면 null) — 껍데기의 「저장하지 않은 변경」 대화창·새로 고침 경고가 이 값을 본다
// · flash = 껍데기가 넘기는 결과 한 줄(새 탐색 수락 등, 한 번) · done = 결과 한 줄을 남기고 상태를 다시 받는다(껍데기 coreDone — 표시 이름 저장).
// R5 에서 라우터째 옮긴다.
import type { AppState } from "./state";

export type UiCtx = {
  reload: () => Promise<unknown>;
  state?: AppState;
  args?: string[];
  setDirty?: (at: string | null) => void;
  flash?: { text: string; bad?: boolean } | null;
  done?: (text: string) => Promise<unknown>;
};
export type ScreenProps = { ctx: UiCtx };
