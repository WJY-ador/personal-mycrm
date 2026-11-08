// 패널 — 머리글(PC 연결 상태 · 닫기) · 메시지 목록 · 상태 한 줄 · 입력 칸(보내기 · 중지 · 8,000자 카운터). ⌘/Ctrl+Enter = 보내기 · Esc = 닫기.
import { useEffect, useRef, type RefObject } from "react";
import { useState } from "react";
import type { WebchatStore } from "./store";
import { TurnView } from "./TurnView";
import { EMPTY, KEEP, PC_OFF, PC_ON, TEXT_MAX, TITLE } from "./text";
import css from "./Webchat.module.css";

export function Panel({ s, inRef }: { s: WebchatStore; inRef: RefObject<HTMLTextAreaElement | null> }) {
  const [choice, setChoice] = useState("");
  const n = [...s.input].length, end = useRef<HTMLDivElement>(null);
  const last = s.turns[s.turns.length - 1];
  useEffect(() => {
    if (!s.open || !s.sid) return;
    void s.loadApprovals();
    const timer = window.setInterval(() => void s.loadApprovals(), 3000);
    return () => window.clearInterval(timer);
  }, [s, s.open, s.sid]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [s.turns.length, last?.answer, last?.tools.length]);
  return (
    <aside className={css.panel} id="webchat" hidden={!s.open} aria-label={TITLE}
      onKeyDown={e => { if (e.key === "Escape") void s.toggle(false); }}>
      <header className={css.head}><h3>{TITLE}</h3>
        <span className={`${css.pc}${s.connected ? ` ${css.up}` : ""}`} role="status">{s.sid ? `${s.provider}${s.model ? `, ${s.model}` : ""}, ${s.connected ? PC_ON : PC_OFF}` : ""}</span>
        {(s.sid || (!s.selectorOpen && !s.loading)) && <button type="button" className="secondary" disabled={s.loading || s.running() || !!s.input.trim()} title={s.running() ? "답이 끝난 뒤 시작할 수 있어요" : s.input.trim() ? "미전송 글을 먼저 보내거나 지우세요" : "새 대화"} onClick={() => { setChoice(""); void s.newConversation(); }}>새 대화</button>}
        <button type="button" className="tertiary" onClick={() => void s.toggle(false)}>닫기</button></header>
      <div className={css.body}>
        {s.loading && <p className={css.empty} role="status">연결 상태를 확인하는 중…</p>}
        {s.selectorOpen && <section className={css.selector} aria-label="새 대화 설정">
          <h4>새 대화</h4>
          <p className={css.empty}>연결된 PC와 사용 가능한 모델을 선택하세요. 대화 중에는 선택을 바꿀 수 없어요.</p>
          {!s.capabilities.devices.length && <p className={css.note} role="status">연결된 호환 PC가 없어요. PC 에이전트를 연결한 뒤 다시 시도하세요.</p>}
          {s.capabilities.devices.map(d => <fieldset key={d.device_id} disabled={!d.connected || s.loading}>
            <legend>{d.device_id}, {d.connected ? "연결됨" : "연결 끊김"}</legend>
            {d.capabilities.flatMap(c => c.models.map(m => {
              const value = `${d.device_id}|${c.provider}|${m ?? ""}`;
              return <label className={css.option} key={value}><input type="radio" name="webchat-provider" value={value} checked={choice === value} onChange={() => setChoice(value)} />
                {c.provider}{m ? `, ${m}` : ""}</label>;
            }))}
          </fieldset>)}
          <div className={css.row}>
            <button type="button" className="tertiary" onClick={() => { s.selectorOpen = false; s.emit(); }}>취소</button>
            <button type="button" className="primary" disabled={!choice || s.loading} onClick={() => { const [device, provider, model] = choice.split("|"); void s.createSession(device, provider, model || null); }}>이 선택으로 시작</button>
          </div>
        </section>}
        {s.readOnly && <p className={css.note} role="status">이전 대화예요. 기록을 읽을 수 있지만 다시 이어서 보내기는 지원하지 않아요. 새 대화를 시작하세요.</p>}
        {s.trimmed && <p className={css.empty}>{s.trimmed}</p>}
        {s.sid && !s.readOnly && <section className={css.approvals} aria-label="확인할 작업">
          <h4>확인이 필요한 작업</h4>
          {s.approvalsLoading && !s.approvals.length && <p className={css.empty} role="status">확인 요청을 불러오는 중…</p>}
          {s.approvalsError && <p className={css.note} role="alert">{s.approvalsError}</p>}
          {!s.approvalsLoading && !s.approvalsError && !s.approvals.length && <p className={css.empty}>대기 중인 확인 요청이 없어요.</p>}
          {s.approvals.map(a => <article className={css.approval} key={a.id}>
            <h5>{a.op}</h5>
            <p className={css.approvalMeta}>{approvalStatus(a.status)}, 대화 턴 {a.turn_id}{a.status === "pending" ? `, 만료 ${a.expires_at}` : a.finished_at ? `, 처리 ${a.finished_at}` : ""}{a.irreversible ? ", 되돌릴 수 없음" : ""}</p>
            <h6>화면에 표시된 내용</h6><pre>{jsonText(a.shown)}</pre>
            <h6>영향</h6><pre>{jsonText(a.impact)}</pre>
            <h6>실행할 전체 매개변수</h6><pre>{jsonText(a.params)}</pre>
            {a.status === "confirmed" && a.result !== null && <><h6>실행 결과</h6><pre>{jsonText(a.result)}</pre></>}
            {a.status === "pending" && s.approvalAction === a.id && <p className={css.empty} role="status">처리 중…</p>}
            {a.status === "pending" && <div className={css.row}>
              <button type="button" className="secondary" disabled={s.approvalsLoading || !!s.approvalAction} onClick={() => void s.actOnApproval(a.id, "cancel")}>취소</button>
              <button type="button" className="primary" disabled={s.approvalsLoading || !!s.approvalAction} onClick={() => void s.actOnApproval(a.id, "confirm")}>확인하고 실행</button>
            </div>}
          </article>)}
          {s.approvalLine && <p className={`${css.line}${s.approvalBad ? ` ${css.bad}` : ""}`} role={s.approvalBad ? "alert" : "status"}>{s.approvalLine}</p>}
          {s.approvalResult && !s.approvals.some(a => a.id === s.approvalResult?.id) && <div className={css.approvalResult} aria-label="실행 결과"><h5>실행 결과</h5><pre>{jsonText(s.approvalResult.result)}</pre></div>}
          <button type="button" className="tertiary" disabled={s.approvalsLoading} onClick={() => void s.loadApprovals()}>목록 새로고침</button>
        </section>}
        {s.turns.length ? s.turns.map(t => <TurnView key={t.id} t={t} />) : s.sid ? <p className={css.empty}>아직 메시지가 없어요.</p> : !s.selectorOpen && <p className={css.empty}>{EMPTY}</p>}
        <div ref={end} />
      </div>
      <p className={`${css.line}${s.bad ? ` ${css.bad}` : ""}`} role="status" aria-live="polite">{s.line || KEEP}</p>
      {s.sid && !s.readOnly && <form className={css.comp} onSubmit={e => { e.preventDefault(); void s.send(); }}>
        <textarea ref={inRef} rows={3} disabled={s.selectorOpen || s.loading} placeholder="무엇이든 말해 보세요" aria-label="대화 입력" value={s.input}
          onChange={e => { s.input = e.target.value; s.emit(); }}
          onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void s.send(); } }} />
        <div className={css.row}>
          <span className={`${css.count}${n > TEXT_MAX ? ` ${css.bad}` : ""}`}>{`${n.toLocaleString()} / ${TEXT_MAX.toLocaleString()}`}</span>
          {s.running() && <button type="button" className="secondary" onClick={() => void s.stop()}>중지</button>}
          <button type="submit" className="primary" disabled={!s.canSend()}>보내기</button></div>
      </form>}
    </aside>
  );
}

function jsonText(value: unknown) {
  try { return JSON.stringify(value, null, 2) ?? "null"; } catch { return String(value); }
}

function approvalStatus(status: string) {
  return status === "pending" ? "확인 대기" : status === "confirmed" ? "확인해 실행함" : "취소함";
}
