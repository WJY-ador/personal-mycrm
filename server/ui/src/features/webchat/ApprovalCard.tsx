// 확인 카드 — 무엇을 하려는지 한 줄 제목(op 한국어 이름) · 상태 · 바뀌는 내용(서버 shown 을 이름과 값의 줄로, 원문은 인용 꼴로).
// shown 은 고쳐 쓰지 않는다: 서버가 준 순서 그대로, 값을 요약하거나 빼지 않는다(표현만 바꾼다). 긴 값은 높이 제한 상자 안에서 스크롤로 전부 보인다. 원본 JSON(shown, impact, params, 결과)은 "자세히" 안에 접는다.
// 버튼과 서버 계약(취소, 확인하고 실행)은 그대로. A5: 되돌릴 수 없는 카드는 표시 한 줄을 두고, 확인하고 실행 뒤 정말 실행을 한 번 더 눌러야 실행한다.
// 보안 검토 1(2026-11-12): 정말 실행은 확인하고 실행과 다른 자리(경고 줄 왼쪽)에 두고, 무장 뒤 1초 비활성, 10초 뒤 해제, 카드 밖을 누르면 바로 해제.
import { useEffect, useRef } from "react";
import { mdhm } from "../../shared/date";
import type { Approval } from "./api";
import type { WebchatStore } from "./store";
import { CARD_AGAIN, CARD_BACK, CARD_CONFIRM, CARD_EMPTY, CARD_HEAD, CARD_IRREVERSIBLE, CARD_MORE, CARD_NULL, CARD_RAW, CARD_REALLY, CARD_SHOWN, CARD_STATUS, OP_NAME } from "./text";
import css from "./Webchat.module.css";

const QUOTE = /인용|원문|본문|문장|^전$|^후$/;   // 사용자가 쓴 글을 그대로 옮긴 값 — 인용 꼴
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
export const jsonText = (value: unknown) => { try { return JSON.stringify(value, null, 2) ?? "null"; } catch { return String(value); } };

function Val({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className={css.muted}>{CARD_NULL}</span>;
  if (Array.isArray(v)) return v.length ? <ul className={css.vals}>{v.map((x, i) => <li key={i}><Val v={x} /></li>)}</ul> : <span className={css.muted}>{CARD_NULL}</span>;
  if (isObj(v)) return <Shown v={v} />;
  if (v === "") return <span className={css.muted}>{CARD_EMPTY}</span>;
  return <>{String(v)}</>;
}

export function Shown({ v }: { v: unknown }) {
  if (!isObj(v)) return <div className={css.kvOne}><Val v={v} /></div>;
  return (
    <dl className={css.kv}>{Object.entries(v).map(([k, x]) => <div key={k}>
      <dt>{k}</dt>
      <dd>{typeof x === "string" && QUOTE.test(k) ? <blockquote>{x}</blockquote> : <Val v={x} />}</dd>
    </div>)}</dl>
  );
}

function Card({ a, s }: { a: Approval; s: WebchatStore }) {
  const when = a.status === "pending" ? `, ${mdhm(a.expires_at)}까지` : a.finished_at ? `, ${mdhm(a.finished_at)}` : "";
  const raw: [string, unknown][] = [["shown", a.shown], ["impact", a.impact], ["params", a.params]];
  if (a.status === "confirmed" && a.result !== null) raw.push(["result", a.result]);
  const armed = a.status === "pending" && a.irreversible && s.approvalArmed === a.id;
  const busy = s.approvalsLoading || !!s.approvalAction;
  const box = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!armed) return;
    const outside = (e: Event) => { if (box.current && !box.current.contains(e.target as Node)) s.disarmApproval(); };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [armed, s]);
  return (
    <article ref={box} className={css.approval} data-op={a.op} data-irreversible={a.irreversible ? "" : undefined}>
      <h5>{OP_NAME[a.op] || a.op}</h5>
      <p className={css.approvalMeta}>{CARD_STATUS[a.status] || a.status}{when}</p>
      {a.irreversible && <p className={css.irreversible} data-irreversible-note="">{CARD_IRREVERSIBLE}</p>}
      <div className={css.shown} data-shown="" tabIndex={0} role="region" aria-label={CARD_SHOWN}><Shown v={a.shown} /></div>
      <details className={css.raw}><summary>{CARD_MORE}</summary>
        {raw.map(([k, v]) => <div key={k}><h6>{CARD_RAW[k]}</h6><pre>{jsonText(v)}</pre></div>)}
      </details>
      {a.status === "pending" && s.approvalAction === a.id && <p className={css.empty} role="status">처리 중…</p>}
      {armed && <div className={css.armRow} data-arm-row="">
        <button type="button" className="primary" disabled={busy || !s.approvalArmReady} onClick={() => void s.actOnApproval(a.id, "confirm")}>{CARD_REALLY}</button>
        <p className={css.irreversible} role="alert">{CARD_AGAIN}</p>
      </div>}
      {a.status === "pending" && (armed ? <div className={css.row} data-card-buttons="">
        <button type="button" className="secondary" disabled={busy} onClick={() => s.disarmApproval()}>{CARD_BACK}</button>
      </div> : <div className={css.row} data-card-buttons="">
        <button type="button" className="secondary" disabled={busy} onClick={() => void s.actOnApproval(a.id, "cancel")}>취소</button>
        <button type="button" className="primary" disabled={busy} onClick={() => void s.actOnApproval(a.id, "confirm")}>{CARD_CONFIRM}</button>
      </div>)}
    </article>
  );
}

// 확인할 것이 있을 때만 보인다(빈 대화에 빈 상자를 두지 않는다)
export function Approvals({ s }: { s: WebchatStore }) {
  const orphan = s.approvalResult && !s.approvals.some(a => a.id === s.approvalResult?.id);
  if (!s.approvals.length && !s.approvalsError && !s.approvalLine && !orphan) return null;
  return (
    <section className={css.approvals} aria-label="확인할 작업">
      <h4>{CARD_HEAD}</h4>
      {s.approvalsError && <p className={css.note} role="alert">{s.approvalsError}</p>}
      {s.approvals.map(a => <Card key={a.id} a={a} s={s} />)}
      {s.approvalLine && <p className={`${css.line}${s.approvalBad ? ` ${css.bad}` : ""}`} role={s.approvalBad ? "alert" : "status"}>{s.approvalLine}</p>}
      {orphan && <details className={css.raw} aria-label="실행 결과"><summary>{CARD_RAW.result}</summary><pre>{jsonText(s.approvalResult?.result)}</pre></details>}
      <button type="button" className="tertiary" disabled={s.approvalsLoading} onClick={() => void s.loadApprovals()}>목록 새로고침</button>
    </section>
  );
}
