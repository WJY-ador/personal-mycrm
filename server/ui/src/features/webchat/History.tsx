// 지난 대화 목록 — GET /api/chat/sessions(최근 50). 열면 끝난 대화는 읽기 전용, 지금 대화는 이어 받는다. 보관 안내 한 줄(서버 30일).
import { mdhm } from "../../shared/date";
import { Sprout } from "../../shared/Sprout";
import type { WebchatStore } from "./store";
import { HISTORY, HISTORY_EMPTY, HISTORY_NOTE, HISTORY_NOW, modelLabel } from "./text";
import css from "./Webchat.module.css";

export function History({ s }: { s: WebchatStore }) {
  return (
    <section className={css.history} aria-label={HISTORY}>
      <p className={css.empty}>{HISTORY_NOTE}</p>
      {s.pastLoading && <Sprout label="지난 대화를 불러오는 중" visible />}
      {s.pastError && <p className={css.note} role="alert">{s.pastError}</p>}
      {!s.pastLoading && !s.pastError && !s.past.length && <p className={css.empty}>{HISTORY_EMPTY}</p>}
      <ul>{s.past.map(p => <li key={p.session_id}>
        <button type="button" className={css.pastItem} onClick={() => void s.openPast(p)} aria-current={p.session_id === s.sid ? "true" : undefined}>
          <span className={css.pastWhen}>{mdhm(p.created_at)}</span>
          <span className={css.pastModel}>{p.provider ? modelLabel(p.provider, p.model) : "이전 형식 대화"}</span>
          {p.status === "active" && <span className={css.pastNow}>{HISTORY_NOW}</span>}
        </button></li>)}</ul>
    </section>
  );
}
