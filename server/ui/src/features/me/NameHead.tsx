// 「나」 머리 — 표시 이름(누르면 인라인 편집, 기존 /api/me/name) + 결과 한 줄(#core-msg — 목록으로 옮긴 뒤의 결과 문구도 여기)
import { useEdit } from "./edit";
import { Editable } from "./Editable";
import { Editor } from "./Editor";
import { meApi } from "./meApi";
import { oldErrText } from "./text";
import css from "./Me.module.css";

export function NameHead({ name }: { name: string }) {
  const { editing, flash } = useEdit();
  const msg = <p className={flash?.bad ? "fok bad" : "fok"} id="core-msg" role="status" aria-atomic="true">{flash?.text}</p>;
  if (editing("name")) return <div className={`hhead ${css.headEdit}`}><Editor />{msg}</div>;
  const spec = { key: "name", done: "표시 이름을 바꿨어요.", errText: oldErrText,
    fields: [{ name: "name", label: "표시 이름", multi: false, orig: name }], save: (d: Record<string, string>) => meApi.name(d.name) };
  return <div className="hhead"><h2 title={name}><Editable spec={spec} cls={css.name}>{name}</Editable></h2>{msg}</div>;
}
