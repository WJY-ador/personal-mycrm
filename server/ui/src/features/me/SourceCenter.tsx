// 출처 가운데 — 이 출처의 내 글(불러온 것만, 더 있으면 「더 보기」 1 = 다음 50편을 받아 이 출처 것만) · 읽고 든 생각 · 이 출처의 활동
import { dOnly, md } from "../../shared/date";
import type { Source } from "../../shared/state";
import { More } from "./More";
import { records, type World } from "./model";
import { SourceActs } from "./SourceActs";
import { REFL_KIND, SRC_KIND, firstLine } from "./text";
import type { useWorld } from "./useWorld";
import css from "./Me.module.css";

type Props = { W: World; x: Source; recs: ReturnType<typeof useWorld>["recs"] };

export function SourceCenter({ W, x, recs }: Props) {
  const mine = records(W).filter(j => j.source_id === x.id), total = W.S.source_counts?.by_source?.[x.id] || 0;
  const rs = (W.S.reflections || []).filter(r => r.source_id === x.id);
  return (
    <>
      <div className={css.kind}>출처 · {SRC_KIND[x.kind] || x.kind}</div>
      <h2 className="title">{x.name}</h2>
      <p className="recmeta">{x.location ? `${x.location} · ` : ""}<a href={`#_obj/source/${x.id}`}>읽고 든 생각 쓰기</a></p>
      <section className={css.sec}><h3>내 글<span className="count">{total}</span></h3>
        {mine.length ? <><More id="src:rec" items={mine.map(j => <li key={j.id}><a href={`#_me/journal/${j.id}`}>{j.title || j.excerpt || "(제목 없음)"}</a><span className="hk">{j.source_date ? dOnly(j.source_date) : md(j.created)}</span></li>)} />
          {total > mine.length && <p className="hint">{`불러온 글만 보여요. 이 출처의 글은 모두 ${total}편이에요.`}</p>}</>
          : <div className="empty">{total ? `불러온 글 중엔 이 출처의 글이 없어요(모두 ${total}편).` : "이 출처의 글이 없어요."}</div>}
        {total > mine.length && recs.next && <>
          <button className="secondary more" type="button" disabled={recs.busy} onClick={() => void recs.more()}>{recs.busy ? "불러오는 중이에요…" : "더 보기"}</button>
          <p className="ferr" role="alert" aria-atomic="true">{recs.err}</p></>}
      </section>
      <section className={css.sec}><h3>읽고 든 생각<span className="count">{rs.length}</span></h3>
        {rs.length ? <More id="src:refl" items={rs.map(r => <li key={r.id}><a href={`#_me/refl/${r.id}`}>{firstLine(r.body) || "(내용 없음)"}</a>
          <span className="hk">{`${REFL_KIND[r.kind] || r.kind} · ${r.review === "reviewed" ? "확인했어요" : "확인 전"}`}</span></li>)} />
          : <div className="empty">아직 없어요.</div>}
      </section>
      <section className={css.sec}><SourceActs W={W} sid={x.id} /></section>
    </>
  );
}
