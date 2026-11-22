// 한 장 그 자리 편집(2026-11-22 구현계획 2절) — 버튼 없이: 저장 = Cmd/Ctrl+Enter 또는 바깥 누르기(바뀌었을 때만), 취소 = Esc.
// 상자엔 저장 원문 그대로(「# 」 머리 포함, 사례 변환 전). 저장은 받은 그대로 「내가 고친 판」 하나로(다듬지 않음).
// 한글 조합 중(isComposing) 키는 무시. 끝내기는 한 번만(Esc 뒤 바깥 누르기, 저장 뒤 바깥 누르기가 겹치지 않게).
// 충돌(STALE)·실패 = 쓰던 글을 상자에 그대로 두고 한 줄 안내.
import { useEffect, useRef, useState } from "react";
import { apiErr } from "../../../shared/api";
import { AXES_QK, axesApi } from "../../../shared/axes";
import { postMsg } from "../../../shared/postErr";
import { queryClient } from "../../../shared/queries";
import { AXIS_TEXT as T } from "../text";
import css from "./Axis.module.css";

type Props = { itemId: string; orig: string; expected: string | null; done: (saved: boolean) => void };

export function AxisEdit({ itemId, orig, expected, done }: Props) {
  const [text, setText] = useState(orig), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null), area = useRef<HTMLTextAreaElement>(null);
  const live = useRef({ text, busy, closed: false });
  live.current.text = text; live.current.busy = busy;

  const close = (saved: boolean) => { if (live.current.closed) return; live.current.closed = true; done(saved); };
  const commit = async () => {
    const L = live.current;
    if (L.closed || L.busy) return;
    if (L.text === orig) return close(false);
    setBusy(true); setErr("");
    try {
      await axesApi.save(itemId, L.text, expected);
      await Promise.all([queryClient.invalidateQueries({ queryKey: AXES_QK }), queryClient.invalidateQueries({ queryKey: ["axes", "page"] })]);
      close(true);
    } catch (x) {
      const e = apiErr(x);
      setErr(e.code === "STALE" ? T.stale : postMsg(e));
      setBusy(false);
    }
  };
  const ref = useRef(commit); ref.current = commit;

  useEffect(() => {
    const n = area.current;
    if (n) { n.focus({ preventScroll: true }); n.setSelectionRange(0, 0); }
    // 바깥 누르기 = 저장(바뀌었을 때만). blur 가 아니라 누르기로 본다 — 창 바꾸기·탭 이동은 저장하지 않는다
    const out = (e: PointerEvent) => { if (box.current && !box.current.contains(e.target as Node)) void ref.current(); };
    document.addEventListener("pointerdown", out, true);
    return () => document.removeEventListener("pointerdown", out, true);
  }, []);

  const key = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || busy) return;
    if (e.key === "Escape") { e.preventDefault(); close(false); }
    else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void commit(); }
  };
  return (
    <div ref={box} className={css.edit} id="axis-edit">
      <p className={css.ehint} id="axis-edit-hint">{busy ? T.saving : T.editHint}</p>
      <textarea ref={area} className={css.ebox} value={text} disabled={busy} aria-label={T.editLabel} aria-describedby="axis-edit-hint axis-edit-err"
        rows={Math.min(40, Math.max(12, text.split("\n").length + 2))} onChange={e => setText(e.target.value)} onKeyDown={key} />
      <p className="ferr" id="axis-edit-err" role="alert" aria-atomic="true">{err}</p>
    </div>
  );
}
