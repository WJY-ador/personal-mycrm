// 탭의 목록 — 행 = (축 색 점) · 코드 · 제목 + 메타 · 연결 수. 커스텀은 머리 오른쪽 선택 상자로 정의(묶음) 하나만 보인다. 행은 링크(이동은 주소, 돌아올 자리만 적어 둔다)
import { useState } from "react";
import { Lock } from "../../shared/Glyph";
import { rowN } from "./links";
import { axColor, axes, type TabRow, type World } from "./model";
import { ME_EMPTY, ME_LOCKED, ME_TAB_LABEL, type MeTab } from "./text";
import { backNav } from "./view";
import css from "./Me.module.css";



export function MeList({ W, tab, rows, sel }: { W: World; tab: MeTab; rows: TabRow[]; sel: TabRow | null }) {
  const ax = tab === "axis" ? axes(W) : [];
  // 커스텀 묶음 = 정의별. 고른 묶음은 화면이 떠 있는 동안만 기억(저장 없음). 열린 항목이 바뀌면 그 항목의 묶음으로 따라간다
  const [pick, setPick] = useState<string | null>(sel?.grp ?? null);
  const [seen, setSeen] = useState(sel?.id);
  if (sel?.id !== seen) { setSeen(sel?.id); if (sel?.grp) setPick(sel.grp); }
  const groups = tab === "custom" ? rows.reduce((m, r) => m.set(r.grp!, { label: r.meta, n: (m.get(r.grp!)?.n || 0) + 1 }), new Map<string, { label: string; n: number }>()) : null;
  const cur = groups ? (pick !== null && groups.has(pick) ? pick : groups.keys().next().value) : undefined;
  const shown = groups ? rows.filter(r => r.grp === cur) : rows;
  return (
    <section className={`hlist ${css.list}`} id="home-list" aria-labelledby="me-list-h">
      <div className="htools"><h3 id="me-list-h">{ME_TAB_LABEL[tab]}{ME_LOCKED.has(tab) && <> <Lock /></>}</h3><span className={css.tools}>
        {groups && groups.size > 1 && <select aria-label="묶음 고르기" value={cur} onChange={e => setPick(e.target.value)}>{[...groups].map(([id, g]) => <option key={id} value={id}>{g.label} {g.n}</option>)}</select>}
        <span className="count">{rows.length}</span></span></div>
      {!rows.length ? <div className="empty">{ME_EMPTY}</div> : (
        <ul className="hrows">{shown.map(r => {
          const i = ax.findIndex(a => a.id === r.id), n = rowN(W, tab, r.id);
          const meta = [tab === "custom" ? "" : r.meta, n === null ? "" : `${tab === "axis" ? "항목과 글" : "연결"} ${n}`].filter(Boolean).join(", ");
          return (
            <li key={r.id}><a href={`#_me/${tab}/${r.id}`} aria-current={sel?.id === r.id ? "true" : undefined} onClick={() => { backNav.fromList = true; backNav.y = window.scrollY; }}>
              <span className="ht">{i >= 0 && <i className={css.axdot} style={{ background: axColor(i) }} />}{r.code && <><span className={css.cd}>{r.code}</span> </>}{r.title}</span>
              <span className="hk">{meta}</span></a></li>
          );
        })}</ul>
      )}
    </section>
  );
}
