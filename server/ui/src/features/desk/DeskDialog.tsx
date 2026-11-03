// 문의 대화창(상시 섬 #ui-desk — 관리자 응답엔 자리가 없다, 서버 Q1 strip). 「문의 보내기」·「개인정보 요청」 = 보내기 폼, 「내 문의」 = 목록 — 한쪽만 보인다.
// 껍데기가 열 때마다 새 ctx(args[0] = send | mine | privacy)로 다시 띄운다. 개인정보 요청 = 종류를 「개인정보 요청」으로 골라 연다.
// 운영자 처리는 /admin/tickets(서버 렌더) — 이 대화창엔 관리자 문의함이 없다.
import { useEffect, useRef, useState } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { queryClient } from "../../shared/queries";
import { DESK_KEY } from "./deskApi";
import { DeskForm } from "./DeskForm";
import { DeskMine } from "./DeskMine";
import css from "./Desk.module.css";

export function DeskDialog({ ctx }: ScreenProps) {
  const dlg = useRef<HTMLDialogElement>(null), ta = useRef<HTMLTextAreaElement>(null);
  const [mine, setMine] = useState(false), [kind, setKind] = useState("bug"), [opened, setOpened] = useState(0);
  useEffect(() => {
    const w = ctx.args?.[0];
    if (!w) return;
    setMine(w === "mine");
    if (w === "privacy") setKind("privacy");
    if (w === "mine") void queryClient.invalidateQueries({ queryKey: DESK_KEY });   // 열 때마다 새 목록
    if (!dlg.current?.open) dlg.current?.showModal?.();
    setOpened(n => n + 1);
  }, [ctx]);
  useEffect(() => { if (opened && !mine) ta.current?.focus(); }, [opened, mine]);
  return (
    <dialog ref={dlg} id="desk-dlg" className={css.dlg} aria-labelledby="desk-dlg-title">
      <div className="dh"><b id="desk-dlg-title">{mine ? "내 문의" : "문의 보내기"}</b>
        <button className="small" type="button" onClick={() => dlg.current?.close?.()}>닫기</button></div>
      <div className="db">
        <DeskForm ctx={ctx} hidden={mine} kind={kind} setKind={setKind} ta={ta} />
        <DeskMine on={mine} />
      </div>
    </dialog>
  );
}
