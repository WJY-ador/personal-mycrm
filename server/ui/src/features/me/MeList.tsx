// 탭의 목록 — 행 = (축 색 점) · 코드 · 제목 + 메타 · 연결 수. 커스텀은 정의별 머리. 행은 링크(이동은 주소, 돌아올 자리만 적어 둔다)
import { Fragment } from "react";
import { rowN } from "./links";
import { axColor, axes, itemsOf, type TabRow, type World } from "./model";
import { ME_EMPTY, ME_LOCKED, ME_TAB_LABEL, type MeTab } from "./text";
import { backNav } from "./view";
import css from "./Me.module.css";



export function MeList({ W, tab, rows, sel }: { W: World; tab: MeTab; rows: TabRow[]; sel: TabRow | null }) {
  const ax = tab === "axis" ? axes(W) : [];
  let grp: string | undefined;
  return (
    <section className={`hlist ${css.list}`} id="home-list" aria-labelledby="me-list-h">
      <div className="htools"><h3 id="me-list-h">{ME_TAB_LABEL[tab]}{ME_LOCKED.has(tab) && <> <span className="lk" aria-label="표준">🔒</span></>}</h3><span className="count">{rows.length}</span></div>
      {!rows.length ? <div className="empty">{ME_EMPTY}</div> : (
        <ul className="hrows">{rows.map(r => {
          const head = tab === "custom" && r.grp !== grp ? <li className={css.grph}>{r.meta}<span className="count">{itemsOf(W, r.grp!).length}</span></li> : null;
          grp = r.grp;
          const i = ax.findIndex(a => a.id === r.id), n = rowN(W, tab, r.id);
          const meta = [tab === "custom" ? "" : r.meta, n === null ? "" : `${tab === "axis" ? "항목·글" : "연결"} ${n}`].filter(Boolean).join(" · ");
          return (
            <Fragment key={r.id}>
              {head}
              <li><a href={`#_me/${tab}/${r.id}`} aria-current={sel?.id === r.id ? "true" : undefined} onClick={() => { backNav.fromList = true; backNav.y = window.scrollY; }}>
                <span className="ht">{i >= 0 && <i className={css.axdot} style={{ background: axColor(i) }} />}{r.code && <><span className={css.cd}>{r.code}</span> </>}{r.title}</span>
                <span className="hk">{meta}</span></a></li>
            </Fragment>
          );
        })}</ul>
      )}
    </section>
  );
}
