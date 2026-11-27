// 주제 항목의 글 한 줄기(주제 잇기, 2026-11-26) — 세션 정리 글이 이름 같은 주제 항목에 붙는다(서버 imports._topic_link).
// 항목 상세(GET /api/item)의 thread = 붙은 글(날짜, 제목, 머리 문단)을 오래된 것부터. 본문은 읽기 토큰. 주제 오브젝트(key topics) 항목만 부른다.
// 하위 목록(2026-11-27 축 > 주제 2절) = 같은 응답의 children — 붙은 글에서 자동 분류로 나온 항목을 오브젝트별 절로(절 이름 = 오브젝트 이름,
// 그 계정에 있고 항목이 있는 것만). 줄 = 날짜, 제목(그 항목 페이지로), 요약 칸(서버가 고른 글자 필드 앞 3개). 새 개념어, 새 결정 없음.
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "../../shared/api";
import { dOnly } from "../../shared/date";
import { rich } from "../../shared/rich";
import { defById, type World } from "./model";
import { LOADING } from "./text";
import css from "./Me.module.css";

export const THREAD = { head: "이 주제의 글", empty: "아직 붙은 글이 없어요.", fail: "글을 불러오지 못했어요." };

export type ThreadRec = { record_id: string; title: string | null; body: string; on: string };
export type ChildRow = { item_id: string; title: string; on: string; object_id: string; object_label: string;
  summary: { key: string; label: string; text: string }[] };
type Topic = { thread: ThreadRec[]; children: ChildRow[] };
const fetchTopic = (id: string) => getJSON<{ thread?: ThreadRec[]; children?: ChildRow[] }>("/api/item?id=" + encodeURIComponent(id))
  .then((j): Topic => ({ thread: j.thread || [], children: j.children || [] }));
const enc = encodeURIComponent;
// 「이 주제의 글」은 머리 문단만(2026-11-27 계획 6절) — 첫 소제목 줄(### 로 시작) 앞까지. 소제목 아래는 종류별 절에 다시 나온다. 전문은 제목 링크
export const headPara = (body: string) => {
  const lines = body.split("\n"), i = lines.findIndex(l => l.startsWith("###"));
  return (i < 0 ? body : lines.slice(0, i).join("\n")).trim();
};

// 서버 순서(오브젝트 → 날짜)를 지키며 오브젝트별로 묶는다
function groups(rows: ChildRow[]) {
  const out: { object_id: string; label: string; rows: ChildRow[] }[] = [];
  for (const r of rows) {
    const g = out.find(x => x.object_id === r.object_id);
    if (g) g.rows.push(r);
    else out.push({ object_id: r.object_id, label: r.object_label, rows: [r] });
  }
  return out;
}

function Children({ W, rows }: { W: World; rows: ChildRow[] }) {
  return <>{groups(rows).map(g => {
    const key = defById(W, g.object_id)?.key, hid = "hchild-" + g.object_id;
    return (
      <section key={g.object_id} className={css.conn} aria-labelledby={hid}>
        <div className="sechead"><h3 id={hid}>{g.label}</h3><span className="hk">{g.rows.length}</span></div>
        <ol className={css.thread}>
          {g.rows.map(r => (
            <li key={r.item_id}>
              <div className={css.threadHead}>
                <span className={css.threadDay}>{dOnly(r.on)}</span>
                {key ? <a href={`#_me/obj/${enc(key)}/${enc(r.item_id)}`}>{r.title}</a> : <span>{r.title}</span>}
              </div>
              {r.summary.length ? <div className={css.threadBody}>{r.summary.map(f =>
                <div key={f.key}><b>{f.label}</b> {rich(f.text)}</div>)}</div> : null}
            </li>
          ))}
        </ol>
      </section>
    );
  })}</>;
}

export function Thread({ W, id }: { W: World; id: string }) {
  const q = useQuery({ queryKey: ["me", "thread", id], queryFn: () => fetchTopic(id) });
  let body;
  if (q.isError) body = <div className="empty">{THREAD.fail} <button className="tertiary" type="button" onClick={() => void q.refetch()}>다시 시도</button></div>;
  else if (q.isPending) body = <p className="hint">{LOADING}</p>;
  else if (!q.data.thread.length) body = <div className="empty">{THREAD.empty}</div>;
  else body = (
    <ol className={css.thread}>
      {q.data.thread.map(r => (
        <li key={r.record_id}>
          <div className={css.threadHead}>
            <span className={css.threadDay}>{dOnly(r.on)}</span>
            <a href={`#_me/journal/${r.record_id}`}>{r.title || "(제목 없음)"}</a>
          </div>
          {headPara(r.body) ? <div className={css.threadBody}>{rich(headPara(r.body))}</div> : null}
        </li>
      ))}
    </ol>
  );
  return (
    <>
      <section className={css.conn} aria-labelledby="hthread-h">
        <div className="sechead">
          <h3 id="hthread-h">{THREAD.head}</h3>
          {q.data?.thread.length ? <span className="hk">{q.data.thread.length}편</span> : null}
        </div>
        {body}
      </section>
      {q.data?.children.length ? <Children W={W} rows={q.data.children} /> : null}
    </>
  );
}
