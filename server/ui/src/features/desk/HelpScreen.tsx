// 설정 「문의 및 개인정보」(#_setup/help) — 문의 대화창을 여는 버튼 셋 + 처리방침. 버튼은 껍데기 data-open 위임이 대화창(#ui-desk)을 연다.
// 관리자(문의 창 없음 — 서버 Q1 strip 과 같은 조건 state.user.admin)는 안내 한 줄만
import type { ScreenProps } from "../../shared/ctx";
import { DESK, DESK_LEAD } from "./text";

export function HelpScreen({ ctx }: ScreenProps) {
  const desk = !ctx.state?.user?.admin;
  return (
    <div className="paper sheet"><h2 className="title">문의 및 개인정보</h2>
      {desk ? <>
        <p className="hint">{DESK_LEAD}</p>
        <div className="hacts" role="group" aria-label="문의"><button className="primary" type="button" data-open="send">문의 보내기</button>
          <button className="secondary" type="button" data-open="mine">내 문의</button><button className="secondary" type="button" data-open="privacy">개인정보 요청</button></div>
      </> : <p className="hint">{DESK.noDesk}</p>}
      <p className="hint"><a href="/privacy">개인정보 처리방침</a></p>
    </div>
  );
}
