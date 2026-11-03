// 요약 블록 틀 — 제목 · (건수·기간) · 본문. full = 두 칸 폭
import type { ReactNode } from "react";
import css from "./Summary.module.css";

export function Blk({ full, title, meta, children }: { full?: boolean; title: string; meta?: string; children: ReactNode }) {
  return (
    <section className={`${css.blk}${full ? " " + css.full : ""}`}>
      <header><h3>{title}</h3>{meta ? <span className="count">{meta}</span> : null}</header>
      {children}
    </section>
  );
}
