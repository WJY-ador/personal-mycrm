// PC 상태 안내(대화 연결 상시 명세 2절, 2026-11-18) — ready 가 아니면 상태 한 줄 + 버튼 하나 + 안 되는 것 고정 한 줄.
// 상태값은 store.chatState() 하나다(모델 고르기 말풍선, 보내기 버튼과 같은 값). 버튼은 사용자가 누를 때만 연다:
// app_off = PC 앱 열기(mycrm:// 링크가 앱을 켠다), ai_not_linked = PC 앱에서 AI 연결, no_pc = PC 앱 받기(/download).
// 앱 창 안(다리 있음)의 ai_not_linked 는 링크 대신 그 자리에서 공급자 연결 버튼(AiLinks)을 보이고, 보일 공급자가 없으면 CLI 가 있어야 한다는 한 줄.
// app_off 버튼 아래에는 이 PC 에서만 열린다는 한 줄.
import { useState } from "react";
import { aiBridge } from "../../shared/desktopPc";
import { AiLinks } from "./AiLinks";
import type { ChatState, WebchatStore } from "./store";
import { AI_NEED_CLI, CHAT_LIMIT, CHAT_OPEN_HERE, CHAT_STATE } from "./text";
import css from "./Webchat.module.css";

export function ConnectGuide({ s, state }: { s: WebchatStore; state: Exclude<ChatState, "ready"> }) {
  const [inApp] = useState(() => !!aiBridge());
  const t = CHAT_STATE[state];
  const local = inApp && state === "ai_not_linked";
  return (
    <section className={css.guide} aria-label={t.line} data-pc={state}>
      <p className={css.guideLine} role="status">{t.line}</p>
      <div className={css.stepActs}>
        {local ? <AiLinks s={s} empty={<p className={css.guideNote}>{AI_NEED_CLI}</p>} />
          : state === "no_pc" ? <a className="btn primary" href={t.href} target="_blank" rel="noopener">{t.act}</a>
          : <a className="btn primary" href={t.href}>{t.act}</a>}
      </div>
      {state === "app_off" && <p className={css.guideNote}>{CHAT_OPEN_HERE}</p>}
      <p>{CHAT_LIMIT}</p>
    </section>
  );
}
