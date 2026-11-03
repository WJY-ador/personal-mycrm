// 폼·버튼 쓰기(옛 corePost·coreFail·coreDone) — 한 번에 하나. 성공 = 결과 한 줄(그 주소 머리, edit store flash) + 옮길 주소(replace) + 다시 받기.
// 실패 = 다시 받을 오류(충돌·없음·이름 필요)면 머리에 문구 + 다시 받기, 아니면 그 자리(key)에 서버 문구(postMsg).
import { useState } from "react";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { useEdit } from "../../shared/edit";
import { postMsg, RELOAD } from "../../shared/postErr";

const here = () => location.hash || "";

export function useWrite(ctx: UiCtx) {
  const { setFlash } = useEdit();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ at: string; key: string; text: string } | null>(null);
  async function go<T>(key: string, call: () => Promise<T>, done: (j: T) => [string, string?]): Promise<boolean> {
    if (busy) return false;
    setBusy(true); setErr(null);
    let j: T;
    try {
      j = await call();
    } catch (x) {
      const e = apiErr(x);
      setBusy(false);
      if (RELOAD.has(e.code)) { setFlash({ at: here(), text: postMsg(e), bad: true }); await ctx.reload(); }
      else setErr({ at: here(), key, text: postMsg(e) });
      return false;
    }
    setBusy(false);
    const [text, to] = done(j);
    setFlash({ at: to || here(), text, bad: false });
    if (to && to !== here()) location.replace(to);
    await ctx.reload();
    return true;
  }
  const errOf = (key: string) => (err && err.key === key && err.at === here() ? err.text : "");
  return { busy, go, errOf, setErr: (key: string, text: string) => setErr({ at: here(), key, text }) };
}
export type Write = ReturnType<typeof useWrite>;
