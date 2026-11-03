// 상세 머리 — 자료 종류 · 제목 · 시각 등 한 줄
import type { ReactNode } from "react";
import css from "./Me.module.css";

export function Head({ kind, title, meta }: { kind: ReactNode; title: ReactNode; meta?: string }) {
  return (
    <>
      <div className={css.kind}>{kind}</div>
      <h2 className="title">{title}</h2>
      {meta ? <p className="recmeta">{meta}</p> : null}
    </>
  );
}
