// 지난 대화 목록 — GET /api/chat/sessions(최근 50). 열면 끝난 대화는 읽기 전용, 지금 대화는 이어 받는다. 보관 안내 한 줄(서버 30일).
// 줄 = 여는 버튼(날짜, 첫 내 말 한 줄, 모델, 지금 대화) + 그 옆 [지우기](버튼 안에 버튼을 넣지 않는다). 지우기는 줄 안에서 한 번 확인한다.
import { mdhm } from "../../shared/date";
import { Sprout } from "../../shared/Sprout";
import type { WebchatStore } from "./store";
import { DEL, DEL_ASK, DEL_BUSY, DEL_CANCEL, HISTORY, HISTORY_EMPTY, HISTORY_NOTE, HISTORY_NOW, PAST_UNTITLED, modelLabel } from "./text";
import css from "./Webchat.module.css";

export function History({ s }: { s: WebchatStore }) {
  return (
    <section className={css.history} aria-label={HISTORY}>
      <p className={css.empty}>{HISTORY_NOTE}</p>
      {s.pastLoading && <Sprout label="지난 대화를 불러오는 중" visible />}
      {s.pastError && <p className={css.note} role="alert">{s.pastError}</p>}
      {!s.pastLoading && !s.pastError && !s.past.length && <p className={css.empty}>{HISTORY_EMPTY}</p>}
      <ul>{s.past.map(p => {
        const id = p.session_id, busy = s.delBusy === id, locked = !!s.delBusy, ask = s.delAsk === id;
        const err = s.delError?.id === id ? s.delError.text : "";
        return <li key={id} className={css.pastRow}>
          <button type="button" className={css.pastItem} onClick={() => void s.openPast(p)} disabled={busy} aria-current={id === s.sid ? "true" : undefined}>
            <span className={css.pastWhen}>{mdhm(p.created_at)}</span>
            <span className={`${css.pastText}${p.first_text ? "" : ` ${css.pastNone}`}`}>{p.first_text || PAST_UNTITLED}</span>
            <span className={css.pastModel}>{p.provider ? modelLabel(p.provider, p.model) : "이전 형식 대화"}</span>
            {p.status === "active" && <span className={css.pastNow}>{HISTORY_NOW}</span>}
          </button>
          {ask ? <div className={css.pastAsk} role="group" aria-label={DEL_ASK}>
            <p>{busy ? DEL_BUSY : DEL_ASK}</p>
            <button type="button" className="secondary" disabled={busy} onClick={() => void s.deletePast(id)}>{DEL}</button>
            <button type="button" className="tertiary" disabled={busy} onClick={() => s.cancelDelete()}>{DEL_CANCEL}</button>
          </div>
            : <button type="button" className={`tertiary ${css.pastDel}`} disabled={locked} onClick={() => s.askDelete(id)}
              aria-label={`${mdhm(p.created_at)} 대화 ${DEL}`}>{DEL}</button>}
          {err && <p className={css.note} role="alert">{err}</p>}
        </li>;
      })}</ul>
    </section>
  );
}
