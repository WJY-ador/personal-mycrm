// 오른쪽 묶음 — 같은 연결 목록을 자료 종류별로. 한 이웃이 여러 관계면 한 줄에 관계를 모은다.
// 제목 = 그 데이터 이름(활동은 행동 · 날짜), 부제 = 관계 + (활동이면) 연결된 사람 별칭 — 가운데가 그 사람이면 별칭은 빼고
import type { Edge, GNode } from "./links";
import { More } from "./More";
import type { World } from "./model";
import { NO_CONN } from "./text";
import { useNames } from "./useNames";
import css from "./Me.module.css";

export function Groups({ W, all, title, self = "" }: { W: World; all: Edge[]; title: string; self?: string }) {
  const name = useNames(W, all.map(e => e.node));
  const groups = new Map<string, Map<string, { node: GNode; rels: string[] }>>();
  for (const e of all) {
    const g = groups.get(e.node.kindName) || new Map();
    const row = g.get(e.node.key) || { node: e.node, rels: [] };
    const rel = `${e.rel}, ${e.dir === "out" ? "가리킴" : "가리켜짐"}`;
    if (!row.rels.includes(rel)) row.rels.push(rel);
    g.set(e.node.key, row);
    groups.set(e.node.kindName, g);
  }
  const who = (n: GNode) => (n.kind === "activity" ? (W.acts[n.id]?.people || []).filter(p => p.id !== self).map(p => p.alias) : []);
  return (
    <aside className={css.groups} aria-label={title}>
      <h3 className={css.gh}>{title}</h3>
      {!all.length ? <div className="empty">{NO_CONN}</div> : [...groups].map(([k, g]) => (
        <section className={css.grp} key={k}>
          <h4>{k}<span className="count">{g.size}</span></h4>
          <More id={"grp:" + k} items={[...g.values()].map(r => (
            <li key={r.node.key}>
              {r.node.href ? <a href={r.node.href}>{name(r.node)}</a> : name(r.node)}
              <span className="hk">{r.rels.concat(who(r.node)).join(", ")}</span>
            </li>
          ))} />
        </section>
      ))}
    </aside>
  );
}
