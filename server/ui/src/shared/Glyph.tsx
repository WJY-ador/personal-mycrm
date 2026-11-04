// 작은 선 아이콘 둘 — 자물쇠(표준 정의 보호)·주의. 이모지(컬러 글꼴) 대신 글자색(currentColor)을 따른다. 접근성 이름은 label 그대로, 글 옆에서 겹치면 hidden.
import type { ReactNode } from "react";

type G = { label?: string; hidden?: boolean };

function Svg({ label, hidden, children }: G & { label: string; children: ReactNode }) {
  return (
    <svg className="lk" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden={hidden || undefined} role={hidden ? undefined : "img"} aria-label={hidden ? undefined : label}>{children}</svg>
  );
}

export const Lock = ({ label = "표준", hidden }: G) => <Svg label={label} hidden={hidden}><rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.2 7V5a2.8 2.8 0 0 1 5.6 0v2" /></Svg>;

export const Caution = ({ label = "주의", hidden }: G) => <Svg label={label} hidden={hidden}><path d="M8 2 15 14H1Z" /><path d="M8 6.5v3.2M8 11.8v.1" /></Svg>;
