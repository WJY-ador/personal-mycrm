// 인라인 편집 칸 — [저장]·[취소] 2개만. 첫 칸 id = hedit-input(껍데기의 「계속 편집」이 이 칸으로 돌아온다). Esc = 취소(요청 0).
// 서버 미리보기(ask)가 있으면 그 문구를 그대로 보이고 [이대로 저장] 한 번 더.
import { useEffect, useRef } from "react";
import { useEdit } from "./edit";
import css from "./Me.module.css";

export function Editor() {
  const { edit: e, set, cancel, save } = useEdit();
  const first = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  useEffect(() => {
    const n = first.current;
    if (n && document.activeElement !== n) { n.focus({ preventScroll: true }); n.setSelectionRange(n.value.length, n.value.length); }
  }, []);
  if (!e) return null;
  const esc = (k: React.KeyboardEvent) => { if (k.key === "Escape" && !e.busy) { k.preventDefault(); cancel(); } };
  return (
    <form className={`${css.editor} fform`} noValidate onSubmit={x => { x.preventDefault(); void save(); }}>
      {e.fields.map((f, i) => {
        const id = i ? `hedit-${f.name}` : "hedit-input";
        const v = e.draft[f.name];
        const common = { id, value: v, disabled: e.busy, "aria-describedby": "hedit-err", onKeyDown: esc,
          onChange: (x: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(f.name, x.target.value), ref: i ? undefined : first };
        return (
          <div key={f.name}>
            <label htmlFor={id}>{f.label}</label>
            {f.multi ? <textarea rows={Math.min(12, Math.max(3, Math.ceil(v.length / 40)))} {...common} />
              : <input className="finput" type="text" {...common} />}
          </div>
        );
      })}
      {e.ask && <p className={css.ask} role="status">{e.ask}</p>}
      <div className="hacts">
        <button className="primary" type="submit" disabled={e.busy}>{e.busy ? "저장하고 있어요…" : e.ask ? "이대로 저장" : "저장"}</button>
        <button className="secondary" type="button" disabled={e.busy} onClick={cancel}>취소</button>
      </div>
      <p className="ferr" id="hedit-err" role="alert" aria-atomic="true">{e.err}</p>
    </form>
  );
}
