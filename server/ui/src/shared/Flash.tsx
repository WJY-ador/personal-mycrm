// 결과 한 줄(옛 #core-msg·coreFlash) — 그 주소에서만 보인다. 껍데기가 넘긴 결과(ctx.flash)도 여기로. 연결 장치·이관·활동이 쓴다.
import { useEffect, useState } from "react";
import type { UiCtx } from "./ctx";

type Msg = { at: string; text: string; bad: boolean };
const here = () => location.hash || "";

export function useFlash(ctx: UiCtx) {
  const [m, setM] = useState<Msg | null>(null);
  useEffect(() => { if (ctx.flash) setM({ at: here(), text: ctx.flash.text, bad: !!ctx.flash.bad }); }, [ctx.flash]);
  return { msg: m && m.at === here() ? m : null, say: (text: string, bad = false, at = here()) => setM({ at, text, bad }) };
}

export function Flash({ msg }: { msg: Msg | null }) {
  return <p className={`fok${msg?.bad ? " bad" : ""}`} role="status" aria-atomic="true">{msg?.text}</p>;
}
