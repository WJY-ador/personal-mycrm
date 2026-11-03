// Setup 「페이지 레이아웃」(#_setup/layout) — 「나」 하위 탭 순서 · 요약 블록 순서. 끌어 놓거나(마우스·터치) 항목에서 Alt + 화살표(키보드).
// 서버 계약 v2(server/layout_registry.json)를 그대로 쓴다 — 블록 이름·기본 배치는 레지스트리(layout/registry.ts 가 props 로 넘긴다).
// 쓰기 = PUT·DELETE /api/me/layout 만(useLay — 한 번에 하나 · 실패 = 마지막 저장 배치 · STALE = 서버 배치).
import type { ScreenProps } from "../../../shared/ctx";
import type { MePage } from "../meApi";
import { LOADING, ME_LOCKED, ME_TAB_LABEL, isTab } from "../text";
import { DndList } from "./DndList";
import { LAY_TEXT, useLay } from "./useLay";
import css from "./Layout.module.css";

type Props = ScreenProps & { def: MePage; blockLabel: Record<string, string> };
const same = (a: string[], b: string[]) => a.join("\n") === b.join("\n");

export function LayoutScreen({ def, blockLabel }: Props) {
  const L = useLay(def);
  if (L.pending) return <div className="paper"><p className="hint">{LOADING}</p></div>;
  const tabs = L.page.tabs, blocks = (L.page.regions.summary || def.regions.summary).map(s => s.c);
  const isDef = same(tabs, def.tabs) && same(blocks, def.regions.summary.map(s => s.c));
  const msg = L.msg.text || (L.api ? "" : LAY_TEXT.noApi);
  const tabLabel = (t: string) => {
    const text = isTab(t) ? ME_TAB_LABEL[t] : t;
    return { text, node: <>{text}{ME_LOCKED.has(t) && <> <span className="lk" aria-hidden="true">🔒</span></>}</> };
  };
  const blockText = (b: string) => { const text = blockLabel[b] || b; return { text, node: text }; };
  return (
    <div className="paper">
      <h2 className="title">페이지 레이아웃 — 「나」</h2>
      <p className="hint" id="lay-help">끌어 놓으면 바로 저장돼요. 키보드는 항목에서 Alt + 화살표로 옮겨요.</p>
      <section className={css.layg}><h3>하위 탭 순서</h3><DndList keys={tabs} horiz label={tabLabel} onMove={(k, to) => L.move("tabs", k, to)} /></section>
      <section className={css.layg}><h3>요약 블록 순서</h3><DndList keys={blocks} label={blockText} onMove={(k, to) => L.move("summary", k, to)} /></section>
      <div className={css.setbar}>
        <p className={L.msg.err ? "ferr" : "fok"} id="lay-msg" role="status" aria-atomic="true">{msg}</p>
        <button className="tertiary" type="button" disabled={isDef || !L.api} onClick={L.reset}>기본으로 되돌리기</button>
      </div>
    </div>
  );
}
