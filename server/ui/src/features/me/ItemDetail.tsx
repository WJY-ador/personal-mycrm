// 항목 상세 — 코드·제목·본문(굵게)·필드 + 동작 + 연결. 제목·본문을 누르면 인라인 편집(둘 다 한 칸에서, [저장] 1번 — 서버 item_edit:
// 제안+적용 한 트랜잭션). 실패 문구는 서버 msg·action 그대로. 확정 기준의 문장을 고쳐도 확정은 유지(서버 규칙).
import { mdhm } from "../../shared/date";
import { rich } from "../../shared/rich";
import { Acts } from "./Acts";
import { Conn } from "./Conn";
import { useEdit, type EditSpec } from "./edit";
import { Editable } from "./Editable";
import { Editor } from "./Editor";
import { FieldRows } from "./FieldRows";
import { Head } from "./Head";
import { meApi } from "./meApi";
import type { Row, World } from "./model";
import { serverErrText } from "./text";
import css from "./Me.module.css";

export function ItemDetail({ W, r, lens, trashOn }: { W: World; r: Extract<Row, { k: "item" }>; lens?: string; trashOn: boolean }) {
  const { editing } = useEdit();
  const x = r.x, key = "item:" + x.id;
  const spec: EditSpec = { key, done: "저장했어요.", errText: serverErrText,
    fields: [{ name: "title", label: "제목", multi: false, orig: x.title || "" }, { name: "body", label: "본문", multi: true, orig: x.body || "", optional: true }],
    save: d => meApi.itemEdit(x.id, x.revision, d.title.trim(), d.body) };
  const meta = [mdhm(r.at), x.semantic_kind === "principle" && x.decision === "confirmed" ? "확정" : ""].filter(Boolean).join(" · ");
  const code = x.code ? <><span className="chip code">{x.code}</span> </> : null;
  const can = x.revision > 0;
  return (
    <>
      {editing(key) ? <><Head kind={r.kind} title={<>{code}{r.title}</>} meta={meta} /><Editor /></> : <>
        <Head kind={r.kind} title={<>{code}{can ? <Editable spec={spec} cls={css.inline}>{r.title}</Editable> : r.title}</>} meta={meta} />
        {x.body ? (can ? <Editable spec={spec} cls={css.body}>{rich(x.body)}</Editable> : <p className={css.body}>{rich(x.body)}</p>) : null}
      </>}
      <FieldRows W={W} it={x} />
      <Acts W={W} r={r} trashOn={trashOn} />
      <Conn W={W} kind="item" id={x.id} lens={lens} />
    </>
  );
}
