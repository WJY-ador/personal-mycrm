// 패널 — 머리글(지난 대화, 새 대화, 닫기) · 대화 정보 한 줄(읽기 전용) · 메시지 목록 또는 지난 대화 목록 · 상태 한 줄 · 입력 칸 하나(모델 고르기 옆).
// 도구 허용 범위, 확인 규칙, 보관 기간은 서버가 정한다. 화면은 보여 주기만 한다(계획 결정 8). Enter = 보내기, Shift+Enter = 줄바꿈, Esc = 닫기.
import { useEffect, useRef, type RefObject } from "react";
import { Sprout } from "../../shared/Sprout";
import { Approvals } from "./ApprovalCard";
import { Composer } from "./Composer";
import { ConnectGuide } from "./ConnectGuide";
import { GrantWait } from "./GrantWait";
import { History } from "./History";
import { choiceKey, type WebchatStore } from "./store";
import { TurnView } from "./TurnView";
import { BUSY_NEW, EMPTY, HISTORY, KEEP, NEW_CHAT, PAST_EMPTY, PAST_NOTE, PC_OFF, PC_ON, TITLE, TOOLS_ONLY, TRIMMED, modelLabel } from "./text";
import css from "./Webchat.module.css";

export function Panel({ s, inRef, dev = "" }: { s: WebchatStore; inRef: RefObject<HTMLTextAreaElement | null>; dev?: string }) {
  const end = useRef<HTMLDivElement>(null);
  const last = s.turns[s.turns.length - 1];
  const live = !!s.sid && !s.readOnly;
  useEffect(() => {
    if (!s.open || !s.sid || s.readOnly) return;
    void s.loadApprovals();
    const timer = window.setInterval(() => void s.loadApprovals(), 3000);
    return () => window.clearInterval(timer);
  }, [s, s.open, s.sid, s.readOnly]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [s.turns.length, last?.answer, last?.tools.length, s.grantNote]);
  const cur = s.shown();
  // PC 상태는 아는 때만: 진행 중 대화 = SSE 의 pc, 새 대화 = 고른 것이 지금 목록(연결된 PC 만)에 있을 때. 지난 대화는 적지 않는다
  const pc = live ? (s.connected ? PC_ON : PC_OFF) : !s.sid && cur && s.choices().some(c => choiceKey(c) === choiceKey(cur)) ? PC_ON : "";
  const busy = s.running() || s.sending;
  // J-F1: 새 대화인데 고를 AI가 하나도 없으면 한 줄 대신 연결 안내 3단계
  const guide = !s.sid && !s.readOnly && !s.loading && s.capsLoaded && !s.grantNote && !s.choices().length;
  return (
    <aside className={css.panel} id="webchat" hidden={!s.open} aria-label={TITLE}
      onKeyDown={e => { if (e.key === "Escape") void s.toggle(false); }}>
      <header className={css.head}><h3>{TITLE}</h3>
        <button type="button" className="tertiary" aria-pressed={s.view === "history"} onClick={() => void s.openHistory()}>{HISTORY}</button>
        <button type="button" className="secondary" disabled={busy} title={busy ? BUSY_NEW : NEW_CHAT} onClick={() => s.newChat()}>{NEW_CHAT}</button>
        <button type="button" className="tertiary" onClick={() => void s.toggle(false)}>닫기</button></header>
      <div className={css.info} aria-label="대화 정보">
        <p role="status">{cur && cur.provider ? `${modelLabel(cur.provider, cur.model)}${pc ? `, ${pc}` : ""}` : ""}</p>
        <p>{KEEP} {TOOLS_ONLY}</p>
      </div>
      <div className={css.body}>
        {s.view === "history" ? <History s={s} /> : <>
          {s.loading && <Sprout label="연결 상태를 확인하는 중" visible />}
          {s.readOnly && <p className={css.past} role="status">{PAST_NOTE}</p>}
          {s.trimmed && <p className={css.empty}>{TRIMMED}</p>}
          {s.turns.length ? s.turns.map(t => <TurnView key={t.id} t={t} />)
            : s.readOnly ? <p className={css.empty}>{PAST_EMPTY}</p> : guide ? <ConnectGuide s={s} /> : !s.loading && !s.grantNote && <p className={css.empty}>{EMPTY}</p>}
          {s.grantNote && <GrantWait s={s} />}
          {live && <Approvals s={s} />}
        </>}
        <div ref={end} />
      </div>
      <p className={`${css.line}${s.bad ? ` ${css.bad}` : ""}`} role="status" aria-live="polite">{s.line}</p>
      {s.view === "history" ? null : s.readOnly ? <div className={css.pastFoot} data-past-foot=""><button type="button" className="primary" onClick={() => s.newChat()}>{NEW_CHAT}</button></div>
        : <Composer s={s} inRef={inRef} dev={dev} />}
    </aside>
  );
}
