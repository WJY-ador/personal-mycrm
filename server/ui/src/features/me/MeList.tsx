// 탭의 목록 — 행 = (축 색 점) · 코드 · 제목 + 메타 · 연결 수. 행은 링크(이동은 주소, 돌아올 자리만 적어 둔다).
// 사용자 오브젝트는 이 목록이 아니라 오브젝트 탭의 목록 보기(obj/ObjTab)
import { Lock } from "../../shared/Glyph";
import { rowN } from "./links";
import { axColor, axes, type TabRow, type World } from "./model";
import { ME_EMPTY, ME_LOCKED, ME_TAB_LABEL, type MeTab } from "./text";
import { backNav } from "./view";
import css from "./Me.module.css";



export function MeList({ W, tab, rows, sel }: { W: World; tab: MeTab; rows: TabRow[]; sel: TabRow | null }) {
  const ax = tab === "axis" ? axes(W) : [];
  return (
    <section className={`hlist ${css.list}`} id="home-list" aria-labelledby="me-list-h">
      <div className="htools"><h3 id="me-list-h">{ME_TAB_LABEL[tab]}{ME_LOCKED.has(tab) && <> <Lock /></>}</h3><span className={css.tools}>
        <span className="count">{rows.length}</span></span></div>
      {!rows.length ? <div className="empty">{ME_EMPTY}</div> : (
        <ul className="hrows">{rows.map(r => {
          const i = ax.findIndex(a => a.id === r.id), n = rowN(W, tab, r.id);
          const meta = [r.meta, n === null ? "" : `${tab === "axis" ? "항목과 글" : "연결"} ${n}`].filter(Boolean).join(", ");
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
