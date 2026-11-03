// 하위 탭 — 순서 = 레이아웃(서버 저장값). 건수 = 그 종류 전체(못 읽은 종류는 숫자 없음). 🔒 = 표준 종류
import { tabCount, type World } from "./model";
import { ME_LOCKED, ME_TAB_LABEL, type MeTab } from "./text";
import css from "./Me.module.css";

export function SubTabs({ W, tabs, cur }: { W: World; tabs: MeTab[]; cur: string }) {
  return (
    <nav className={css.sub} aria-label="「나」 하위 탭">{tabs.map(t => {
      const n = tabCount(W, t), on = t === cur;
      return (
        <a key={t} href={`#_me/${t}`} aria-current={on ? "page" : undefined} className={on ? css.on : undefined}>
          {ME_TAB_LABEL[t]}{ME_LOCKED.has(t) && <span className="lk" title="표준" aria-label="표준">🔒</span>}{n !== null && <span className={css.n}>{n}</span>}
        </a>
      );
    })}</nav>
  );
}
