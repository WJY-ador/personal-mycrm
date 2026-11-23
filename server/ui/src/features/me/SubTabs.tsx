// 하위 탭 — 순서 = 레이아웃(서버 저장값). 건수 = 그 종류 전체(못 읽은 종류는 숫자 없음). 자물쇠 = 표준 종류.
// 오브젝트 탭(obj:<key>) = 사용자 오브젝트마다 하나, 이름 = 그 오브젝트 label, 주소 #_me/obj/<key>
// 2026-11-23 탭 줄 대신 셀렉트 하나(보기 고르기). 고르면 그 탭 주소로 간다. 지금 탭이 목록에 없으면(상세 단독 화면 등) 고르지 않은 옵션이 보인다.
// 옵션 안에는 그림을 넣을 수 없어 자물쇠는 셀렉트에 없다
import { tabCount, type World } from "./model";
import { objTabKey, tabLabel } from "./text";
import css from "./Me.module.css";

export const tabHref = (t: string) => (objTabKey(t) ? `#_me/obj/${encodeURIComponent(objTabKey(t))}` : `#_me/${t}`);

export const PICK_NONE = "보기 고르기";

export function SubTabs({ W, tabs, cur }: { W: World; tabs: string[]; cur: string }) {
  const known = tabs.includes(cur);
  return (
    <nav className={css.sub} aria-label="나 보기">
      <label htmlFor="me-view-pick">보기</label>
      <select id="me-view-pick" value={known ? cur : ""} onChange={e => { if (e.target.value) location.hash = tabHref(e.target.value); }}>
        {!known && <option value="" disabled>{PICK_NONE}</option>}
        {tabs.map(t => {
          const n = tabCount(W, t), name = tabLabel(W.S.definitions, t);
          return <option key={t} value={t}>{n !== null ? `${name} (${n})` : name}</option>;
        })}
      </select>
    </nav>
  );
}
