// 판단 상세 — 문장 · (검토할 판단이면) 재검토 표시 · 동작([고쳐서 남기기] = 인라인 편집) · 근거 글 인용(굵게) · 연결
import { mdhm } from "../../shared/date";
import { rich } from "../../shared/rich";
import { Acts } from "./Acts";
import { Conn } from "./Conn";
import { useEdit } from "../../shared/edit";
import { Editor } from "../../shared/Editor";
import { Head } from "./Head";
import { records, type Row, type World } from "./model";
import { ReviewNote } from "../../shared/ReviewNote";
import css from "./Me.module.css";

export function CandDetail({ W, r, trashOn }: { W: World; r: Extract<Row, { k: "cand" }>; trashOn: boolean }) {
  const { editing } = useEdit();
  const x = r.x, rec = records(W).find(j => j.id === x.record_id);
  return (
    <>
      <Head kind={r.kind} title={x.text} meta={mdhm(r.at)} />
      {x.status === "pending" && <ReviewNote review={x.review} />}
      {editing("cand:" + x.id) ? <Editor /> : <Acts W={W} r={r} trashOn={trashOn} />}
      <div className={css.quote}>근거 · <a href={`#_me/journal/${x.record_id}`}>{rec ? rec.title || "(제목 없음)" : "근거 글"}</a><br /><mark>{rich(x.quote)}</mark></div>
      <Conn W={W} kind="cand" id={x.id} />
    </>
  );
}
