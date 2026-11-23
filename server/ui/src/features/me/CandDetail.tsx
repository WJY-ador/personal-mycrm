// 판단 상세 — 문장 · (검토할 판단이면) 재검토 표시 · 동작 · 근거 글 인용(굵게) · 연결
// 아직 안 정한 판단(재검토 표시 없음)은 문장을 눌러 고친다. 저장하면 고친 문장으로 확정까지 된다(Acts 의 candSpec).
import { mdhm } from "../../shared/date";
import { rich } from "../../shared/rich";
import { Acts, candSpec } from "./Acts";
import { Editable } from "../../shared/Editable";
import { Conn } from "./Conn";
import { useEdit } from "../../shared/edit";
import { Editor } from "../../shared/Editor";
import { Head } from "./Head";
import { records, type Row, type World } from "./model";
import { ReviewNote } from "../../shared/ReviewNote";
import css from "./Me.module.css";

export function CandDetail({ W, r, trashOn }: { W: World; r: Extract<Row, { k: "cand" }>; trashOn: boolean }) {
  const { editing } = useEdit();
  const x = r.x, rec = records(W).find(j => j.id === x.record_id), spec = candSpec(x);
  const can = x.status === "pending" && !x.review;   // 재검토 표시가 있으면 남길 수 없어 고치기도 없다
  const on = editing(spec.key);
  return (
    <>
      <Head kind={r.kind} title={can && !on ? <Editable spec={spec} look="inline">{x.text}</Editable> : x.text} meta={mdhm(r.at)} />
      {x.status === "pending" && <ReviewNote review={x.review} />}
      {on ? <Editor /> : <Acts W={W} r={r} trashOn={trashOn} />}
      <div className={css.quote}>근거: <a href={`#_me/journal/${x.record_id}`}>{rec ? rec.title || "(제목 없음)" : "근거 글"}</a><br /><mark>{rich(x.quote)}</mark></div>
      <Conn W={W} kind="cand" id={x.id} />
    </>
  );
}
