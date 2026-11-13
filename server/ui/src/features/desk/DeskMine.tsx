// 내 문의 — 본인 글·상태만(GET /api/feedback). 오류 자동 Case(via auto)는 종류 칸에 「자동으로 보낸 오류 보고」와 횟수. 접수일을 누르면 상세 대화창(DeskTicket)이 위에 겹쳐 열린다. 사용자 글은 글자로만 넣는다
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { clip } from "../../shared/clip";
import { md } from "../../shared/date";
import { DESK_KEY, deskApi } from "./deskApi";
import { DeskTicket } from "./DeskTicket";
import { DESK, DESK_CHIP, TICKET_STATUS, kindLabel } from "./text";
import css from "./Desk.module.css";

export function DeskMine({ on }: { on: boolean }) {
  const q = useQuery({ queryKey: DESK_KEY, queryFn: deskApi.list, enabled: on });
  const [open, setOpen] = useState({ id: "", n: 0 });
  const list = q.data?.tickets || [];
  return (
    <div id="desk-mine" hidden={!on}>
      <p className="hint">처리 상태와 운영자 답변을 볼 수 있어요. 접수일을 누르면 열려요.</p>
      <div className={css.wrap}><table className={css.tbl}><thead><tr><th scope="col">접수일</th><th scope="col">종류</th><th scope="col">상태</th><th scope="col">답변</th><th scope="col">최근 갱신</th><th scope="col">글</th></tr></thead>
        <tbody>{list.map(t => (
          <tr key={t.id}><td><button type="button" className={css.open} aria-haspopup="dialog" onClick={() => setOpen(o => ({ id: t.id, n: o.n + 1 }))}>{md(t.created)}</button></td>
            <td>{kindLabel(t)}</td><td><span className={`chip ${DESK_CHIP[t.status] || ""}`}>{TICKET_STATUS[t.status] || t.status}</span></td>
            <td>{t.has_reply ? "있음" : "—"}</td><td>{md(t.public_updated) || "—"}</td><td>{clip(t.text, 60)}</td></tr>
        ))}</tbody></table></div>
      {q.isSuccess && !list.length && <p className="empty">{DESK.empty}</p>}
      <p role="alert" className={`blocked ${css.msg}`}>{q.isError ? DESK.listFail : ""}</p>
      {open.id && <DeskTicket key={open.n} id={open.id} onClose={() => setOpen(o => ({ id: "", n: o.n }))} />}
    </div>
  );
}
