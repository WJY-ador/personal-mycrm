// 「표시 이름 바꾸기」 대화창(계정 메뉴 — 상시 섬 #ui-namedlg, 모든 역할). 껍데기가 열 때마다 새 ctx(args[0] = "open")로 다시 띄운다 —
// 그때 지금 이름을 채우고 문구를 비운 뒤 연다. 저장하면 닫고 결과 한 줄(ctx.done)
import { useEffect, useRef, useState } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { NameForm } from "./NameForm";
import css from "./Name.module.css";

export function NameDialog({ ctx }: ScreenProps) {
  const dlg = useRef<HTMLDialogElement>(null), input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(""), [err, setErr] = useState("");
  useEffect(() => {
    if (ctx.args?.[0] !== "open") return;
    setValue(ctx.state?.user?.display_name || "");
    setErr("");
    if (!dlg.current?.open) dlg.current?.showModal?.();
    input.current?.focus();
  }, [ctx]);
  const close = () => dlg.current?.close?.();
  return (
    <dialog ref={dlg} id="name-dlg" className={css.dlg} aria-labelledby="name-dlg-title"><div className="dh"><b id="name-dlg-title">표시 이름 바꾸기</b>
      <button className="small" type="button" onClick={close}>닫기</button></div><div className="db">
      <NameForm ctx={ctx} id="name-dlg" input={input} value={value} setValue={setValue} err={err} setErr={setErr} onSaved={close}
        acts={busy => <div className={`acts ${css.acts}`}><button className="primary" type="submit" disabled={busy}>저장</button>
          <button className="tertiary" type="button" onClick={close}>취소</button></div>} />
    </div></dialog>
  );
}
