// 요약 — 블록 순서·props = 레이아웃 저장값의 regions.summary(서버 v2). 모르는 블록 id 는 건너뛴다(레지스트리 밖). 버튼 0(이동 링크만)
import type { Slot } from "../meApi";
import type { World } from "../model";
import type { Blocks } from "./block";
import css from "./Summary.module.css";

export function Summary({ W, slots, blocks, statsFail }: { W: World; slots: Slot[]; blocks: Blocks; statsFail: boolean }) {
  return (
    <div className={css.sum} id="me-summary">
      {slots.filter(s => blocks[s.c]).map((s, i) => { const B = blocks[s.c]; return <B key={`${s.c}${i}`} p={s.p || {}} W={W} statsFail={statsFail} />; })}
    </div>
  );
}
