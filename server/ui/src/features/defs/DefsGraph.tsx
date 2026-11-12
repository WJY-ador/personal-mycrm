// 구조 그래프 — 서버 structure_svg.render 결과(S.structure_svg, 정본)를 React 요소로 옮겨 그린다(HTML 문자열 꽂기 0 · script·on*·바깥 링크 제거).
// 원·선(<a href="#dmo-…">)을 누르면 주소를 바꾸지 않고 목록의 같은 id 로 간다(라우트 해시 앱 — #dmo-o1 은 탭이 아니다).
import { useMemo, type MouseEvent } from "react";
import { svgToReact } from "../../shared/domReact";
import { originCategories, originChip } from "../../shared/origin";
import type { AppState } from "../../shared/state";
import { FIXHINT } from "./text";

export function DefsGraph({ S, jump }: { S: AppState; jump: (id: string) => void }) {
  const svg = typeof S.structure_svg === "string" ? S.structure_svg : "";
  const el = useMemo(() => svgToReact(svg), [svg]);
  const click = (e: MouseEvent) => {
    const a = (e.target as Element).closest("a");
    if (!a) return;
    e.preventDefault();
    const id = (a.getAttribute("href") || "").slice(1);
    if (/^dmo-/.test(id)) jump(id);
  };
  return (
    <section className="sec" id="dgraph" aria-label="구조 그래프">
      <div className="dlegend">{originCategories(S).map(k => <span key={k}><i className={`o-${k}`} />{originChip(S, k)[1]}</span>)}
        <span>점선 고리 = 표준 정의 보호</span><span>선 = 관계(화살표 없음), 세 갈래 = 여러(N), 두 줄 = 하나(1), 참조를 가진 쪽이 N</span></div>
      {el ? <div className="dmo" onClick={click}>{el}</div> : <div className="empty">그래프를 읽지 못했어요. 목록으로 보세요. {FIXHINT}</div>}
      <p className="hint" style={{ margin: ".6rem 0 0" }}>원을 누르면 목록의 그 자료 종류로, 선을 누르면 그 관계로 가요.</p></section>
  );
}
