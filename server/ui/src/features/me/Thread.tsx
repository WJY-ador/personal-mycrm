// 주제 항목의 글 한 줄기(주제 잇기, 2026-11-26) — 세션 정리 글이 이름 같은 주제 항목에 붙는다(서버 imports._topic_link).
// 항목 상세(GET /api/item)의 thread = 붙은 글(날짜, 제목, 본문)을 오래된 것부터. 본문은 읽기 토큰. 주제 오브젝트(key topics) 항목만 부른다.
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../../shared/api";
import { dOnly } from "../../shared/date";
import { rich } from "../../shared/rich";
import { LOADING } from "./text";
import css from "./Me.module.css";

export const THREAD = { head: "이 주제의 글", empty: "아직 붙은 글이 없어요.", fail: "글을 불러오지 못했어요." };

export type ThreadRec = { record_id: string; title: string | null; body: string; on: string };
const fetchThread = (id: string) => getJSON<{ thread?: ThreadRec[] }>("/api/item?id=" + encodeURIComponent(id)).then(j => j.thread || []);

export function Thread({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["me", "thread", id], queryFn: () => fetchThread(id) });
  let body;
  if (q.isError) body = <div className="empty">{THREAD.fail} <button className="tertiary" type="button" onClick={() => void q.refetch()}>다시 시도</button></div>;
  else if (q.isPending) body = <p className="hint">{LOADING}</p>;
  else if (!q.data.length) body = <div className="empty">{THREAD.empty}</div>;
  else body = (
    <ol className={css.thread}>
      {q.data.map(r => (
        <li key={r.record_id}>
          <div className={css.threadHead}>
            <span className={css.threadDay}>{dOnly(r.on)}</span>
            <a href={`#_me/journal/${r.record_id}`}>{r.title || "(제목 없음)"}</a>
          </div>
          <div className={css.threadBody}>{rich(r.body)}</div>
        </li>
      ))}
    </ol>
  );
  return (
    <section className={css.conn} aria-labelledby="hthread-h">
      <div className="sechead">
        <h3 id="hthread-h">{THREAD.head}</h3>
        {q.data?.length ? <span className="hk">{q.data.length}편</span> : null}
      </div>
      {body}
    </section>
  );
}
