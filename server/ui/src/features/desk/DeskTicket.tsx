// 내 문의 하나(GET /api/feedback/<id> — 본인 것만): 보낸 글 · 공개 답변 · 공개 이력. 내부 메모·내부 이력은 서버가 주지 않는다. 열 때마다 새로 받는다
import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { mdhm } from "../../shared/date";
import { deskApi, type TicketHist } from "./deskApi";
import { DESK, TICKET_KIND, TICKET_STATUS } from "./text";
import css from "./Desk.module.css";

const st = (v: string | null) => TICKET_STATUS[v || ""] || v || "";
export const histText = (h: TicketHist) =>
  h.kind === "deleted" ? "삭제 완료" : h.kind === "status" ? `상태 ${st(h.from_val)} → ${st(h.to_val)}` : "운영자 답변이 바뀌었어요";

export function DeskTicket({ id, onClose }: { id: string; onClose: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const q = useQuery({ queryKey: ["desk", "one", id], queryFn: () => deskApi.one(id), staleTime: 0, gcTime: 0 });
  useEffect(() => { if (!dlg.current?.open) dlg.current?.showModal?.(); }, []);
  const j = q.data;
  const title = j ? `내 문의 · ${TICKET_KIND[j.kind] || j.kind}` : "내 문의";
  let body;
  if (q.isError && !j) body = <p className="blocked">{apiErr(q.error).msg || DESK.oneFail}</p>;
  else if (!j) body = <p className="hint">불러오는 중이에요…</p>;
  else body = (
    <div className={css.tk}>{q.isError ? <p className="blocked" role="alert">{apiErr(q.error).msg || DESK.oneFail}</p> : null}<h3>보낸 글</h3><p className={css.txt}>{j.text}</p>
      <h3>운영자 답변</h3><p className={css.txt}>{j.reply || DESK.noReply}</p><p className="hint">{j.reply_at ? mdhm(j.reply_at) + " 답변" : ""}</p>
      <h3>처리 이력</h3><ul>{j.history.map((h, i) => <li key={i}>{mdhm(h.at)} · {histText(h)}</li>)}</ul>
      <p className="hint">{j.history.length ? "" : DESK.noHist}</p></div>
  );
  return (
    <dialog ref={dlg} className={css.tkdlg} aria-labelledby="desk-tk-title" onClose={onClose}>
      <div className="dh"><div><b id="desk-tk-title">{title}</b><div className={`recmeta ${css.meta}`}>{j ? `${mdhm(j.created)} 접수 · ${st(j.status)}` : ""}</div></div>
        <button className="small" type="button" onClick={() => dlg.current?.close?.()}>닫기</button></div>
      <div className="db">{body}</div>
    </dialog>
  );
}
