// 긴 목록 — 5줄 + 「더 N」 1(누르면 그 목록만 펼침, 쓰기 없음). 펼침은 같은 가운데 데이터에 머무는 동안만. 펼치면 새로 보인 첫 줄로 초점
import { useEffect, useRef, type ReactNode } from "react";
import { useView } from "./view";
import css from "./Me.module.css";

export const SHOW = 5;

export function More({ id, items }: { id: string; items: ReactNode[] }) {
  const v = useView(), ul = useRef<HTMLUListElement>(null), was = useRef(v.isOpen(id));
  const all = v.isOpen(id) || items.length <= SHOW;
  useEffect(() => {
    if (all && !was.current) ul.current?.querySelectorAll<HTMLElement>(":scope > li a")[SHOW]?.focus();
    was.current = all;
  }, [all]);
  return (
    <>
      <ul className={css.connlist} ref={ul}>{all ? items : items.slice(0, SHOW)}</ul>
      {!all && <button className="tertiary mmore" type="button" onClick={() => v.open(id)}>{`더 ${items.length - SHOW}`}</button>}
    </>
  );
}
