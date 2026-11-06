// Setup 「페이지 레이아웃」(#_setup/layout) — 「나」 하위 탭 순서 · 요약 블록 순서. 끌어 놓거나(마우스·터치) 항목에서 Alt + 화살표(키보드).
// 서버 계약 v2(server/layout_registry.json)를 그대로 쓴다 — 블록 이름·기본 배치는 레지스트리(layout/registry.ts 가 props 로 넘긴다).
// 쓰기 = PUT·DELETE /api/me/layout 만(useLay — 한 번에 하나 · 실패 = 마지막 저장 배치 · STALE = 서버 배치).
// 자리 알림 = 옮길 때마다(버튼·Alt + 화살표·끌어 놓기) 이름 + 새 자리(1부터) 한 번. 저장 상태는 #lay-msg 가 따로 —
// 저장이 끝나도 자리 알림은 다시 그리지 않고, 저장 실패로 되돌리면·기본으로 되돌리면 지운다. 움직임 없음(정적 문구).
// 보이는 문구 = 옮긴 그 행의 이름 바로 아래(aria-hidden — 읽기는 #lay-pos 가 맡아 두 번 읽지 않는다). 고정·붙는 상자가 없어 다른 행 버튼을 덮지 않는다.
// 읽는 문구 = 늘 있는 #lay-pos(.sr, role="status" polite atomic) — 같은 문구도 새 노드(key)로 다시 읽힌다.
import { useState } from "react";
import type { ScreenProps } from "../../../shared/ctx";
import { Lock } from "../../../shared/Glyph";
import type { MePage } from "../meApi";
import { LOADING, ME_LOCKED, ME_TAB_LABEL, isTab } from "../text";
import { DndList } from "./DndList";
import { LAY_TEXT, useLay } from "./useLay";
import css from "./Layout.module.css";

type Props = ScreenProps & { def: MePage; blockLabel: Record<string, string> };
const same = (a: string[], b: string[]) => a.join("\n") === b.join("\n");
type Grp = "tabs" | "summary";

export function LayoutScreen({ def, blockLabel }: Props) {
  const L = useLay(def);
  // grp·key = 문구를 붙일 행 · n 이 바뀌면 새 노드 = 같은 문구도 다시 읽힌다
  const [pos, setPos] = useState<{ text: string; n: number; grp?: Grp; key?: string }>({ text: "", n: 0 });
  if (L.pending) return <div className="paper"><p className="hint">{LOADING}</p></div>;
  const tabs = L.page.tabs, blocks = (L.page.regions.summary || def.regions.summary).map(s => s.c);
  const isDef = same(tabs, def.tabs) && same(blocks, def.regions.summary.map(s => s.c));
  const msg = L.msg.text || (L.api ? "" : LAY_TEXT.noApi);
  const posText = L.msg.err ? "" : pos.text;   // 저장 실패·STALE 로 되돌렸으면 옮긴 자리는 더 맞지 않다
  // 옮긴 행이면 이름 바로 아래에 보이는 문구 — text(aria-label·버튼 이름)는 그대로, 읽기는 #lay-pos 만
  const inline = (grp: Grp, k: string) => posText && pos.grp === grp && pos.key === k
    ? <span className={css.rowpos} data-lay-pos="" aria-hidden="true">{posText}</span> : null;
  const tabLabel = (t: string) => {
    const text = isTab(t) ? ME_TAB_LABEL[t] : t;
    return { text, node: <>{text}{ME_LOCKED.has(t) && <> <Lock hidden /></>}{inline("tabs", t)}</> };
  };
  const blockText = (b: string) => { const text = blockLabel[b] || b; return { text, node: <>{text}{inline("summary", b)}</> }; };
  // 옮김 = useLay.move 가 바꿨을 때만(경계·제자리 = false) — 새 자리는 move 와 같은 방식으로 끝에 맞춘다
  const moved = (grp: Grp, len: number, label: (k: string) => { text: string }) => (k: string, to: number) => {
    if (!L.move(grp, k, to)) return false;
    const at = Math.max(0, Math.min(len - 1, to)) + 1;
    setPos(p => ({ text: `${label(k).text} ${at}번째로 옮겼어요.`, n: p.n + 1, grp, key: k }));
    return true;
  };
  return (
    <div className="paper">
      <h2 className="title">페이지 레이아웃 — 「나」</h2>
      <p className="hint" id="lay-help">끌어 놓으면 바로 저장돼요. 키보드는 항목에서 Alt + 화살표로 옮겨요.</p>
      <p className="sr" id="lay-pos" role="status" aria-live="polite" aria-atomic="true">{posText ? <span key={pos.n}>{posText}</span> : null}</p>
      <section className={css.layg}><h3>하위 탭 순서</h3><DndList keys={tabs} horiz label={tabLabel} onMove={moved("tabs", tabs.length, tabLabel)} /></section>
      <section className={css.layg}><h3>요약 블록 순서</h3><DndList keys={blocks} label={blockText} onMove={moved("summary", blocks.length, blockText)} /></section>
      <div className={css.setbar}>
        <p className={L.msg.err ? "ferr" : "fok"} id="lay-msg" role="status" aria-atomic="true">{msg}</p>
        <button className="tertiary" type="button" disabled={isDef || !L.api} onClick={() => { setPos(p => ({ text: "", n: p.n })); L.reset(); }}>기본으로 되돌리기</button>
      </div>
    </div>
  );
}
