// 최근 변경 5 — 항목(고친 시각)·내 글(받은 시각)·읽고 든 생각(고친 시각). 불러온 범위(S) 안에서
import { mdhm, timeOf } from "../../../shared/date";
import { objLabel, records, tabOfItem } from "../model";
import { firstLine, ME_EMPTY } from "../text";
import { Blk } from "./Blk";
import type { BlockProps } from "./block";
import css from "./Summary.module.css";

export function Recent({ W }: BlockProps) {
  const xs: { at: string; kind: string; title: string; href: string }[] = [];
  for (const it of W.S.items || []) if (it.revision) xs.push({ at: it.updated_at || it.created_at, kind: objLabel(W, it.object_id),
    title: (it.code ? it.code + " " : "") + (it.title || "(제목 없음)"), href: `#_me/${tabOfItem(W, it)}/${it.id}` });
  for (const r of records(W)) xs.push({ at: r.created, kind: "내 글", title: r.title || r.excerpt || "(제목 없음)", href: `#_me/journal/${r.id}` });
  for (const x of W.S.reflections || []) xs.push({ at: x.updated || x.created, kind: "읽고 든 생각", title: firstLine(x.body) || "(내용 없음)", href: `#_me/refl/${x.id}` });
  const top = xs.map((x, i) => [x, i] as const).sort((a, b) => timeOf(b[0].at) - timeOf(a[0].at) || a[1] - b[1]).slice(0, 5).map(p => p[0]);
  return (
    <Blk full title="최근 변경">
      {top.length ? <ul className={`hrows ${css.recent}`}>{top.map(x => (
        <li key={x.href}><a href={x.href}><span className="ht"><span className="chip">{x.kind}</span> {x.title}</span><span className="hk">{mdhm(x.at)}</span></a></li>
      ))}</ul> : <div className="empty">{ME_EMPTY}</div>}
    </Blk>
  );
}
