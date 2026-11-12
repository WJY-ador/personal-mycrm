// 읽고 든 생각 상세 — 출처 이름 · 시각·확인 상태 · 본문(누르면 인라인 편집, 저장하면 확인 전으로) · 동작 · 연결
import { mdhm } from "../../shared/date";
import { rich } from "../../shared/rich";
import { Acts } from "./Acts";
import { Conn } from "./Conn";
import { useEdit } from "../../shared/edit";
import { Editable } from "../../shared/Editable";
import { Editor } from "../../shared/Editor";
import { Head } from "./Head";
import { meApi } from "./meApi";
import { srcName, type Row, type World } from "./model";
import { oldErrText } from "./text";
import css from "./Me.module.css";

export function ReflDetail({ W, r, trashOn }: { W: World; r: Extract<Row, { k: "refl" }>; trashOn: boolean }) {
  const { editing } = useEdit();
  const x = r.x, key = "refl:" + x.id;
  const spec = { key, done: "저장했어요. 확인 전으로 돌아갔어요.", errText: oldErrText,
    fields: [{ name: "body", label: "읽고 든 생각", multi: true, orig: x.body }],
    save: (d: Record<string, string>) => meApi.reflection(x.id, { source_id: x.source_id, kind: x.kind, body: d.body, expected_revision: x.revision }) };
  return (
    <>
      <Head kind={r.kind} title={srcName(W, x.source_id)} meta={[mdhm(r.at), x.review === "reviewed" ? "확인했어요" : "확인 전"].join(", ")} />
      {editing(key) ? <Editor /> : <><Editable spec={spec} look="body" cls={css.body}>{rich(x.body)}</Editable><Acts W={W} r={r} trashOn={trashOn} /></>}
      <Conn W={W} kind="refl" id={x.id} />
    </>
  );
}
