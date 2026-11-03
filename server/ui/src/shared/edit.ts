// 쓰기 상태(「나」·자료 종류 공용 — R4-2 에 features/me 에서 올림) — 편집은 한 번에 하나(값을 눌러 인라인), 버튼 동작은 한 번에 하나(중복 방지). 쓰기는 [저장]·동작 버튼을 눌렀을 때만 —
// 선택·입력·취소·Esc·전환은 요청 0. 다시 그려도 쓰던 글은 남는다(draft). 고친 게 있는 동안 껍데기에 주소를 알린다(setDirty →
// 「저장하지 않은 변경」 대화창·새로 고침 경고). 주소가 바뀌어 여기 왔으면(= 껍데기가 이동을 허락) 편집을 버린다.
import { createContext, useContext, useEffect, useState } from "react";
import { apiErr, type ApiError } from "./api";
import type { UiCtx } from "./ctx";

export const EMPTY_DRAFT = "비어 있어요. 내용을 적은 뒤 저장해 주세요.";

export type EField = { name: string; label: string; multi: boolean; orig: string; optional?: boolean };
export type EditSpec = {
  key: string; fields: EField[]; done: string;
  save: (d: Record<string, string>) => Promise<unknown>;
  errText: (e: ApiError) => string;
  confirm?: (d: Record<string, string>) => Promise<string>;   // 저장 전 서버 미리보기 — 빈 문자열이면 확인 없이 저장
};
type Edit = EditSpec & { at: string; draft: Record<string, string>; busy: boolean; err: string; ask: string };
type Act = { at: string; busy: boolean; ok: string; err: string };
export type Flash = { at: string; text: string; bad: boolean; shown?: string };   // shown = 처음 보인 주소(한 번만)

// routing = 이번 그리기가 주소를 replace 하는 중(그 주소에선 결과 문구를 「보였다」고 치지 않는다 — 옛 coreFlash 처럼 옮긴 뒤 한 번)
// home = 주소가 비었을 때의 자리(「나」 = #_me)
export function useEditStore(ctx: UiCtx, routing = false, home = "") {
  const here = () => location.hash || home;
  const [edit, setEdit] = useState<Edit | null>(null);
  const [act, setAct] = useState<Act | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const at = here();
  const live = edit && edit.at === at ? edit : null;
  const dirty = !!live && live.fields.some(f => live.draft[f.name] !== f.orig);
  useEffect(() => { if (edit && edit.at !== at) setEdit(null); }, [edit, at]);
  useEffect(() => { ctx.setDirty?.(dirty ? at : null); }, [ctx, dirty, at]);
  useEffect(() => () => ctx.setDirty?.(null), [ctx]);
  useEffect(() => { if (ctx.flash) setFlash({ at: here(), text: ctx.flash.text, bad: !!ctx.flash.bad }); }, [ctx.flash]);
  // 결과 문구 — 그 주소(또는 그 아래로 replace 된 주소)에서 처음 한 번 보이고, 다른 곳으로 가면 사라진다
  const showFlash = !!flash && (flash.shown ? flash.shown === at : at === flash.at || at.startsWith(flash.at + "/"));
  useEffect(() => { if (flash && showFlash && !flash.shown && !routing) setFlash({ ...flash, shown: at }); }, [flash, showFlash, routing, at]);

  const start = (s: EditSpec) => {
    if (live) return document.getElementById("hedit-input")?.focus();
    setAct(null);
    setEdit({ ...s, at, draft: Object.fromEntries(s.fields.map(f => [f.name, f.orig])), busy: false, err: "", ask: "" });
  };
  const set = (name: string, v: string) => setEdit(e => (e ? { ...e, draft: { ...e.draft, [name]: v }, ask: "" } : e));
  const cancel = () => setEdit(e => (e && !e.busy ? null : e));

  async function save() {
    const e = live;
    if (!e || e.busy) return;
    if (e.fields.some(f => !f.optional && !e.draft[f.name].trim())) return setEdit({ ...e, err: EMPTY_DRAFT });
    if (!dirty) return setEdit(null);   // 바뀐 게 없으면 요청하지 않는다
    setEdit({ ...e, busy: true, err: "" });
    try {
      if (e.confirm && !e.ask) {
        const ask = await e.confirm(e.draft);
        if (ask) return setEdit({ ...e, busy: false, err: "", ask });
      }
      await e.save(e.draft);
    } catch (x) {
      const err = apiErr(x);
      setEdit({ ...e, busy: false, ask: "", err: e.errText(err) });
      if (err.code === "CONFLICT") await ctx.reload();
      return;
    }
    setEdit(null);
    setAct({ at: e.at, busy: false, ok: e.done, err: "" });
    await ctx.reload();
  }

  // 버튼 한 번 = 쓰기 한 번. after = 성공 뒤 갈 주소(그 데이터가 목록에서 빠질 때) — 결과 문구는 그 주소 머리에 한 번
  async function run(call: () => Promise<unknown>, done: string, errText: (e: ApiError) => string, after = "") {
    if ((act && act.busy) || live) return;
    setAct({ at, busy: true, ok: "", err: "" });
    try {
      await call();
    } catch (x) {
      const err = apiErr(x);
      setAct({ at, busy: false, ok: "", err: errText(err) });
      if (err.code === "CONFLICT") await ctx.reload();
      return;
    }
    if (after) { setAct(null); setFlash({ at: after, text: done, bad: false }); location.replace(after); }
    else setAct({ at, busy: false, ok: done, err: "" });
    await ctx.reload();
  }

  return { edit: live, act: act && act.at === at ? act : null, flash: showFlash ? flash : null,
    start, set, cancel, save, run, setFlash, editing: (key: string) => live?.key === key };
}

export type EditStore = ReturnType<typeof useEditStore>;
export const EditCtx = createContext<EditStore | null>(null);
export const useEdit = () => useContext(EditCtx)!;
