// 구조 이름 공유 동의(옛 namesBox — 계정 메뉴 항목을 옮김, 같은 API). 문구는 껍데기 계정 메뉴의 사용자 전용 구간(user 표식)에서 읽는다 —
// 관리자 /app 은 서버가 그 구간을 빼므로 이 상자도 없다(번들에 그 글자를 두지 않는다). 안내 줄은 React 요소로 옮겨 그린다(HTML 문자열 꽂기 0).
import { useState } from "react";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { domToReact } from "../../shared/domReact";
import { postMsg } from "../../shared/postErr";
import { stdApi } from "./stdApi";

export function Names({ ctx }: { ctx: UiCtx }) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const item = document.getElementById("acct-names");
  if (!item) return null;
  const label = (item.firstChild?.textContent || "").trim(), note = document.querySelector("#acct-menu .acct-note");
  const on = ctx.state?.user?.struct_names === true;
  async function toggle() {
    setBusy(true); setErr("");
    try { await stdApi.names(!on); } catch (x) { setBusy(false); setErr(postMsg(apiErr(x))); return; }
    await ctx.reload();
    setBusy(false);
  }
  return (
    <section className="sec" aria-labelledby="names-h"><h3 id="names-h">{label}</h3>
      {note ? <p className="hint">{[...note.childNodes].map((n, i) => domToReact(n, `nt${i}`))}</p> : null}
      <button type="button" className="secondary" aria-pressed={on} disabled={busy} onClick={toggle}>{label} <span className="tech">{on ? "켜짐" : "꺼짐"}</span></button>
      <p className="ferr" id="names-err" role="alert" aria-atomic="true">{err}</p></section>
  );
}
