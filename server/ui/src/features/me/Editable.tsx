// 값을 눌러 편집 — 키보드(Tab·Enter·Space)로도. 편집할 수 있는 값만 버튼 모양(겉모양은 글).
// block = 문단이 든 값(기록 본문) — <button> 안엔 문단을 못 넣어 같은 동작의 role=button 상자로
import type { ReactNode } from "react";
import { useEdit, type EditSpec } from "./edit";
import css from "./Me.module.css";

type Props = { spec: EditSpec; cls?: string; block?: boolean; children: ReactNode };

export function Editable({ spec, cls = "", block = false, children }: Props) {
  const { start } = useEdit();
  const c = `${css.hval} ${cls}`;
  if (!block) return <button type="button" className={c} title="눌러서 고치기" onClick={() => start(spec)}>{children}</button>;
  return (
    <div role="button" tabIndex={0} className={c} title="눌러서 고치기" onClick={() => start(spec)}
      onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); start(spec); } }}>
      {children}
    </div>
  );
}
