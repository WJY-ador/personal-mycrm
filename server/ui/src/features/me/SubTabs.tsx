// 하위 탭 — 순서 = 레이아웃(서버 저장값). 건수 = 그 종류 전체(못 읽은 종류는 숫자 없음). 자물쇠 = 표준 종류.
// 오브젝트 탭(obj:<key>) = 사용자 오브젝트마다 하나, 이름 = 그 오브젝트 label, 주소 #_me/obj/<key>
import { Lock } from "../../shared/Glyph";
import { tabCount, type World } from "./model";
import { ME_LOCKED, isTab, objTabKey, tabLabel } from "./text";
import css from "./Me.module.css";

export const tabHref = (t: string) => (objTabKey(t) ? `#_me/obj/${encodeURIComponent(objTabKey(t))}` : `#_me/${t}`);

export function SubTabs({ W, tabs, cur }: { W: World; tabs: string[]; cur: string }) {
  return (
    <nav className={css.sub} aria-label="나 하위 탭">{tabs.map(t => {
      const n = tabCount(W, t), on = t === cur;
      return (
        <a key={t} href={tabHref(t)} aria-current={on ? "page" : undefined} className={on ? css.on : undefined}>
          {tabLabel(W.S.definitions, t)}{isTab(t) && ME_LOCKED.has(t) && <Lock />}{n !== null && <span className={css.n}>{n}</span>}
        </a>
      );
    })}</nav>
  );
}
