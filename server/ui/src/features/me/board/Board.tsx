// 한판 상세(#_me/board/<한판 항목 id>, 루틴판 쓰는 중 카드에서) — 핵심 한 줄 · 세 단 들어온 것(a, b…) | 내가 정한 것(이어서) | 이렇게 나왔다(소제목 1, 2…).
// 넓은 화면 = 출처에서 소제목으로 선, 소제목에 마우스를 올리거나 포커스하면 그 출처 카드와 선만 진하게(나머지 흐리게). 좁은 화면 = 선 없이 위아래, 「나온 곳」 글자만.
// 읽기만(GET /api/me/routine/<id>) — 없는 항목·남의 항목 = 404 → 열 수 없음 한 줄.
import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../../shared/api";
import { dOnly } from "../../../shared/date";
import { meApi } from "../meApi";
import { GONE, LOADING } from "../text";
import { useMobile } from "../view";
import { BoardLinks } from "./BoardLinks";
import { BT, RefCard, SubCard } from "./BoardCards";
import { boardModel, refKey } from "./boardModel";
import css from "./Board.module.css";

const BACK = "#_me/summary";

export function Board({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["me", "routine-board", id], queryFn: () => meApi.routineDetail(id), retry: false });
  const mobile = useMobile(), [hot, setHot] = useState<number | null>(null);
  const d = q.data, M = useMemo(() => (d ? boardModel(d) : null), [d]);
  const wrap = (body: ReactNode) => <section className={`paper ${css.board}`} id="board-detail" aria-live="polite">
    <p className="hback"><a href={BACK}>{BT.back}</a></p>{body}</section>;
  if (q.isError) return wrap(<div className="empty">{apiErr(q.error).status === 404 ? GONE : BT.fail}</div>);
  if (!d || !M) return wrap(<p className="hint">{LOADING}</p>);
  const lit = new Set(hot === null ? [] : M.from[hot] || []);
  const col = (title: string, refs: typeof d.inflow, none: string) => <div className={css.dcol}><h4>{title}</h4>
    <ul className={css.cards}>{refs.length ? refs.map(r => { const k = M.syms[refKey(r)]; return <RefCard key={k} r={r} k={k} on={lit.has(k)} />; })
      : <li className={css.none}>{none}</li>}</ul></div>;
  return wrap(<>
    <h2 className={css.keyline}>{d.board.key_line || d.board.title}</h2>
    <p className={css.meta}>{dOnly(d.board.date)}</p>
    <div className={`${css.grid}${hot !== null ? " " + css.focus : ""}`} id="board-grid">
      {!mobile && <BoardLinks links={M.links} hot={hot} ver={String(d.subheads.length)} />}
      {col(BT.inflow, d.inflow, BT.noIn)}
      {col(BT.decided, d.decided, BT.noDec)}
      <div className={css.dcol}><h4>{BT.out}</h4>
        <ul className={css.cards}>{d.subheads.length ? d.subheads.map((s, o) =>
          <SubCard key={s.item_id} s={s} o={o} from={M.from[o]} on={hot === o} hover={v => setHot(h => (v ? o : h === o ? null : h))} />)
          : <li className={css.none}>{BT.noSub}</li>}</ul></div>
    </div>
    {d.missing_sources > 0 ? <p className="hint">{BT.missing(d.missing_sources)}</p> : null}
  </>);
}
