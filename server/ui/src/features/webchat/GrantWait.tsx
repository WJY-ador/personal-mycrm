// PC 허용 대기 — "PC 앱에서 허용을 눌러 주세요"(기다림 캐릭터와 함께). 끝 = 허용되면 사라지고 대화가 시작된다.
// 승인 없이 끝남(취소, 창 닫힘), 시간 초과, PC 꺼짐 = 각자 한 문장 + 다시 요청. PC 의 취소는 서버에 오지 않아 창이 닫힌 것과 같은 문장이다.
import { Sprout } from "../../shared/Sprout";
import type { WebchatStore } from "./store";
import { GRANT, GRANT_CANCEL, GRANT_RETRY, modelLabel } from "./text";
import css from "./Webchat.module.css";

export function GrantWait({ s }: { s: WebchatStore }) {
  const g = s.grant;
  const waiting = s.waiting();
  return (
    <section className={css.grant} aria-label="PC 허용">
      {waiting ? <Sprout label={GRANT[s.grantNote]} visible /> : <p className={css.grantEnd} role="alert">{GRANT[s.grantNote]}</p>}
      {g && <p className={css.grantFor}>{modelLabel(g.provider, g.model)}</p>}
      {s.grantNote !== "approved" && <div className={css.row}>
        {!waiting && <button type="button" className="primary" onClick={() => void s.retryGrant()}>{GRANT_RETRY}</button>}
        <button type="button" className="tertiary" onClick={() => s.cancelGrant()}>{GRANT_CANCEL}</button>
      </div>}
    </section>
  );
}
