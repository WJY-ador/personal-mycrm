import { mdhm } from "../../shared/date";
import type { TrashAct, TrashItem } from "./trashApi";
import { TRASH_KIND } from "./text";
import css from "./Trash.module.css";

type Props = { x: TrashItem; busy: boolean; onAct: (act: TrashAct, x: TrashItem) => void };

// 행 = 종류 · 제목 또는 별칭 · 삭제 시각 · 복원 가능 기한 + [복원]·[영구 삭제]
export function TrashRow({ x, busy, onAct }: Props) {
  return (
    <li className={css.row}>
      <div className={css.main}>
        <span className="chip">{x.object_label || TRASH_KIND[x.kind] || x.kind}</span> <b>{x.title || "(제목 없음)"}</b>
        <p className="recmeta">{`${mdhm(x.trashed_at)} 삭제, 복원 가능 기한 ${mdhm(x.purge_at)}`}</p>
      </div>
      <div className={`hacts ${css.acts}`} role="group" aria-label="휴지통 동작">
        <button className="primary" type="button" disabled={busy} onClick={() => onAct("restore", x)}>복원</button>
        <button className="secondary" type="button" disabled={busy} onClick={() => onAct("purge", x)}>영구 삭제</button>
      </div>
    </li>
  );
}
