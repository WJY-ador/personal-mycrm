// 값을 눌러 편집 — 키보드(Tab·Enter·Space)로도. 편집할 수 있는 값만 버튼 모양(겉모양은 글).
// block = 문단이 든 값(기록 본문) — <button> 안엔 문단을 못 넣어 같은 동작의 role=button 상자로. 연필(EditMark)은 늘 보인다(터치 화면 hover 없음)
import type { ReactNode } from "react";
import { EditMark } from "./EditMark";
import { useEdit, type EditSpec } from "./edit";
import css from "./Edit.module.css";

// look = 값 모양(name = 한 줄 머리 · inline = 글 안 · body = 문단 · doc = 문단 상자) · cls = 부르는 화면의 글 모양(크기·줄 간격)
type Props = { spec: EditSpec; look?: "name" | "inline" | "body" | "doc"; cls?: string; block?: boolean; children: ReactNode };

export function Editable({ spec, look, cls = "", block = false, children }: Props) {
  const { start } = useEdit();
  const c = [css.hval, look ? css[look] : "", cls].filter(Boolean).join(" ");
  if (!block) return <button type="button" className={c} title="눌러서 고치기" onClick={() => start(spec)}>{children}<EditMark /></button>;
  return (
    <div role="button" tabIndex={0} className={c} title="눌러서 고치기" onClick={() => start(spec)}
      onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); start(spec); } }}>
      {children}<EditMark corner />
    </div>
  );
}
