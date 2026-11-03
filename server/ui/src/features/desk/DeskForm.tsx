// 문의 보내기 폼(대화창 안 — 「내 문의」로 바꿔도 남아 있다: 쓰던 글·고른 종류 유지). 길이 = UTF-8 바이트(서버 db.LIMIT_TICKET 과 같은 단위).
// 보낸 자리(page) = 보낼 때의 주소(model.deskPage). 실패 = 서버 문구 그대로(없으면 화면 문구) · 성공 = 글 비움 + 「내 문의」 다시 받기
import { useState, type FormEvent, type RefObject } from "react";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { queryClient } from "../../shared/queries";
import { DESK_KEY, deskApi } from "./deskApi";
import { bytes, deskPage } from "./model";
import { DESK, DESK_LEAD, DESK_MAX, DESK_NOTICE, TICKET_KIND } from "./text";
import css from "./Desk.module.css";

type Props = { ctx: UiCtx; hidden: boolean; kind: string; setKind: (k: string) => void; ta: RefObject<HTMLTextAreaElement | null> };

export function DeskForm({ ctx, hidden, kind, setKind, ta }: Props) {
  const [text, setText] = useState(""), [status, setStatus] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const n = bytes(text), over = n > DESK_MAX;
  async function send(e: FormEvent) {
    e.preventDefault();
    if (!text.trim() || over) return;
    setError(""); setStatus(DESK.sending); setBusy(true);
    try {
      await deskApi.send(kind, text, deskPage(ctx.state, location.hash));
    } catch (x) {
      const f = apiErr(x);
      setBusy(false);
      if (f.code === "UNAUTHORIZED") return;
      setStatus(""); setError(f.msg || DESK.sendFail);
      return;
    }
    setBusy(false); setText(""); setStatus(DESK.sent);
    void queryClient.invalidateQueries({ queryKey: DESK_KEY });
  }
  return (
    <form id="desk-form" noValidate hidden={hidden} onSubmit={send}>
      <p className="hint">{DESK_LEAD}</p>
      <fieldset className={css.kinds}><legend className="sr">문의 종류</legend>
        {Object.entries(TICKET_KIND).map(([k, l]) => (
          <label key={k}><input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} /> {l}</label>
        ))}
      </fieldset>
      <label htmlFor="desk-text" className="sr">문의 글</label>
      <textarea ref={ta} id="desk-text" className={css.text} name="text" rows={4} aria-describedby="desk-notice desk-count" value={text} onChange={e => setText(e.target.value)} />
      <div className={css.row}><span id="desk-count" className={`count ${css.count}${over ? " " + css.over : ""}`} aria-live="polite">{`${n} / ${DESK_MAX} 바이트${over ? " — 너무 길어요" : ""}`}</span>
        <button className="primary" type="submit" disabled={busy || over || !text.trim()}>보내기</button></div>
      <p id="desk-notice" className={css.note}>{DESK_NOTICE} <a href="/privacy">개인정보 처리방침</a></p>
      <p className={css.status} role="status">{status}</p><p role="alert" className={`blocked ${css.msg}`}>{error}</p>
    </form>
  );
}
