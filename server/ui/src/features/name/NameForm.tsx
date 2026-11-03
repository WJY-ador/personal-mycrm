// 표시 이름 폼 하나(이름 관문·「표시 이름 바꾸기」 대화창 공용 — 옛 coreSubmit). 빈 값만 여기서 막고 길이 규칙은 서버 문구 그대로.
// 성공 = ctx.done(결과 한 줄 + 상태 다시 받기 — 관문이면 대시보드가 열린다) · 다시 불러올 오류(충돌·없음) = 그 자리 문구 + ctx.reload
import { useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { postMsg, RELOAD } from "../../shared/postErr";
import { saveName } from "./nameApi";
import { NAME_EMPTY, NAME_HELP, NAME_SAVED } from "./text";

type Props = { ctx: UiCtx; id: string; input: RefObject<HTMLInputElement | null>; value: string; setValue: (v: string) => void;
  err: string; setErr: (e: string) => void; acts: (busy: boolean) => ReactNode; onSaved?: () => void };

export function NameForm({ ctx, id, input, value, setValue, err, setErr, acts, onSaved }: Props) {
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (!value.trim()) { setErr(NAME_EMPTY); return; }
    setBusy(true);
    try {
      await saveName(value);
    } catch (x) {
      const f = apiErr(x);
      setBusy(false);
      if (f.code === "UNAUTHORIZED") return;
      setErr(postMsg(f));
      if (RELOAD.has(f.code)) void ctx.reload();
      return;
    }
    setBusy(false);
    onSaved?.();
    void (ctx.done ? ctx.done(NAME_SAVED) : ctx.reload());
  }
  return (
    <form className="fform" id={`${id}-form`} noValidate onSubmit={submit}>
      <label htmlFor={`${id}-input`}>표시 이름</label>
      <input ref={input} className="finput" id={`${id}-input`} name="display_name" type="text" autoComplete="nickname" aria-describedby={`${id}-help`}
        value={value} onChange={e => setValue(e.target.value)} />
      <p className="hint" id={`${id}-help`}>{NAME_HELP}</p>
      {acts(busy)}
      <p className="ferr" role="alert" aria-atomic="true">{err}</p>
    </form>
  );
}
