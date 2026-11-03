// 내 구조 설정(옛 renderDefs) — #_setup/structure(옛 #_settings·#structure/defs 는 껍데기가 이 주소로). 목록 · 그래프(기본) 전환은 이 화면에 머무는 동안만
// (주소·저장소에 두지 않는다 — 다른 화면에 갔다 오면 그래프). 구조 이름 공유 동의 · 고급(공통 구조 적용 검토, 열림 상태는 다시 그려도 유지).
// 정의를 바꾸는 일은 연결한 AI 대화에서 — 이 화면엔 정의 편집이 없다.
import { useEffect, useState } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { DefsGraph } from "./DefsGraph";
import { DefsList } from "./DefsList";
import { Names } from "./Names";
import { StdPreview } from "./StdPreview";
import { FIXHINT } from "./text";

let advOpen = false;   // 옛 stdAdvOpen — 페이지가 살아 있는 동안 「고급」 열림 유지

export function DefsScreen({ ctx }: ScreenProps) {
  const S = ctx.state!;
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const [hit, setHit] = useState(""), [adv, setAdv] = useState(advOpen);
  useEffect(() => {
    if (!hit) return;
    const n = document.getElementById(hit);
    n?.scrollIntoView?.({ block: "start" });
    n?.focus({ preventScroll: true });
    const t = setTimeout(() => setHit(""), 1600);
    return () => clearTimeout(t);
  }, [hit]);
  const st = S.structure;
  if (!st || !Array.isArray(st.objects)) return <div className="empty">구조 정의를 읽지 못했어요. {FIXHINT}</div>;
  const m = (k: "list" | "graph") => <button type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>{k === "list" ? "목록" : "그래프"}</button>;
  return (
    <div className="paper"><div className="eyebrow">내 구조 설정</div>
      <p className="hint" style={{ margin: ".3rem 0 .9rem" }}>정의를 바꾸는 일은 연결한 AI 대화에서 해요.</p>
      <div className="dmode" role="group" aria-label="구조 정의 보기 방식">{m("list")}{m("graph")}</div>
      <div id="dlist" hidden={mode !== "list"}><DefsList S={S} hit={hit} /></div>
      <div hidden={mode !== "graph"}><DefsGraph S={S} jump={id => { setMode("list"); setHit(id); }} /></div>
      <Names ctx={ctx} />
      <details className="fold" id="std-adv" open={adv} onToggle={e => { advOpen = (e.currentTarget as HTMLDetailsElement).open; setAdv(advOpen); }}><summary>고급</summary>
        <StdPreview ctx={ctx} /></details>
    </div>
  );
}
