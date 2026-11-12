// 연결 목록 보기 — 상한 없이 직접 연결 전부(이름 · 종류 · 관계 · 방향)
import type { Edge } from "./links";
import { useNames } from "./useNames";
import type { World } from "./model";
import css from "./Me.module.css";

export function ConnList({ W, all }: { W: World; all: Edge[] }) {
  const name = useNames(W, all.map(e => e.node));
  return (
    <ul className={css.connlist}>
      {all.map((e, i) => (
        <li key={i}>
          {e.node.href ? <a href={e.node.href}>{name(e.node)}</a> : name(e.node)}
          <span className="hk">{`${e.node.kindName}, ${e.rel}, ${e.dir === "out" ? "이 데이터가 가리킴" : "이 데이터를 가리킴"}`}</span>
        </li>
      ))}
    </ul>
  );
}
