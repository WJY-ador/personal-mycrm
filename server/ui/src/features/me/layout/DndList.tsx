// 끌어 놓는 순서 줄 하나(옛 app.html 끌기·Alt + 화살표 그대로) — 포인터(마우스·터치·펜) 하나로 끄는 동안은 줄 안에서 자리만 바꾸고, 놓을 때 한 번 저장.
// 터치·펜은 손잡이(⠿)에서만 — 나머지는 화면 스크롤. 키보드 = 항목에서 Alt + 화살표. 항목은 key 로 그려 다시 그려도 포커스가 그 항목에 남는다.
import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import css from "./Layout.module.css";

type Props = { keys: string[]; horiz?: boolean; label: (k: string) => { text: string; node: ReactNode }; onMove: (key: string, to: number) => boolean };
const STEP: Record<string, number> = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 };

export function DndList({ keys, horiz, label, onMove }: Props) {
  const [drag, setDrag] = useState<{ key: string; order: string[] } | null>(null);
  const start = useRef(-1), ol = useRef<HTMLOListElement>(null);
  const order = drag ? drag.order : keys;

  function down(e: PointerEvent<HTMLLIElement>, k: string) {
    if (e.button !== 0) return;
    if (e.pointerType !== "mouse" && !(e.target as HTMLElement).closest(`.${css.grip}`)) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    start.current = keys.indexOf(k);
    setDrag({ key: k, order: keys.slice() });
    e.preventDefault();
  }
  function moveTo(e: PointerEvent<HTMLLIElement>) {
    if (!drag || !ol.current) return;
    const sibs = [...ol.current.children].filter(x => (x as HTMLElement).dataset.layKey !== drag.key);
    let at = sibs.length;
    for (let i = 0; i < sibs.length; i++) {
      const r = sibs[i].getBoundingClientRect();
      const before = horiz ? (e.clientY < r.top ? true : e.clientY > r.bottom ? false : e.clientX < r.left + r.width / 2) : e.clientY < r.top + r.height / 2;
      if (before) { at = i; break; }
    }
    const rest = drag.order.filter(k => k !== drag.key);
    rest.splice(at, 0, drag.key);
    if (rest.join("\n") !== drag.order.join("\n")) setDrag({ key: drag.key, order: rest });
  }
  function drop(cancel: boolean) {
    if (!drag) return;
    const end = drag.order.indexOf(drag.key);
    setDrag(null);
    if (!cancel && end !== start.current) onMove(drag.key, end);
  }
  function key(e: KeyboardEvent<HTMLLIElement>, k: string, i: number) {
    const d = STEP[e.key];
    if (!e.altKey || !d) return;
    e.preventDefault();
    onMove(k, i + d);
  }

  return (
    <ol ref={ol} className={`${css.dnd} ${horiz ? css.h : css.v}`}>
      {order.map((k, i) => {
        const l = label(k);
        return (
          <li key={k} tabIndex={0} data-lay-key={k} className={drag?.key === k ? css.dragging : undefined} aria-label={`${l.text} — ${i + 1}번째`} aria-describedby="lay-help"
            onPointerDown={e => down(e, k)} onPointerMove={moveTo} onPointerUp={() => drop(false)} onPointerCancel={() => drop(true)} onKeyDown={e => key(e, k, i)}>
            <span className={css.grip} aria-hidden="true">⠿</span><span>{l.node}</span>
          </li>
        );
      })}
    </ol>
  );
}
