// 읽고 든 생각 카드(옛 reflCard·reflBadge·reviewBtn) — 확인 상태 · 유형 · (출처) · 본문 · [확인했어요|확인 전으로] · 열기. 출처 하나·전체 목록이 같이 쓴다
import { md } from "../../shared/date";
import { rich } from "../../shared/rich";
import type { Refl } from "../../shared/state";
import { srcName } from "./model";
import { objApi } from "./objApi";
import type { P } from "./props";
import { REFL_KIND, REFL_REVIEW } from "./text";
import type { Write } from "./useWrite";
import { useWrite } from "./useWrite";
import css from "./Objects.module.css";

export const Badge = ({ x }: { x: Refl }) => { const b = REFL_REVIEW[x.review] || REFL_REVIEW.pending; return <span className={`badge ${b[0]}`}>{b[1]}</span>; };

// 확인 버튼 — 확인했어요는 판단 확정이 아니다(문구 그대로)
export function ReviewBtn({ x, w, k }: { x: Refl; w: Write; k: string }) {
  const to = x.review !== "reviewed";
  const go = () => void w.go(k, () => objApi.reflReview(x.id, to, x.revision), () => [to ? "확인했어요로 표시했어요. 판단 확정은 아니에요." : "확인 전으로 돌렸어요."]);
  return <button className={to ? "primary" : "secondary"} type="button" disabled={w.busy} onClick={go}>{to ? "확인했어요" : "확인 전으로"}</button>;
}

export function ReflCards({ ctx, S, xs, compact }: P & { xs: Refl[]; compact: boolean }) {
  const w = useWrite(ctx);
  return (
    <div className="cards">{xs.map(x => (
      <article key={x.id} className={`card ${css.rcard}`}>
        <div className="labels"><Badge x={x} /><span className="chip">{REFL_KIND[x.kind] || x.kind}</span>{compact ? null : <span className="chip src">{srcName(S, x.source_id)}</span>}</div>
        <p className={`${css.rbody}${compact ? " " + css.clip : ""}`}>{rich(x.body)}</p>
        <div className={css.pacts}><ReviewBtn x={x} w={w} k={x.id} /><a className="btn" href={`#_obj/reflection/${x.id}`}>열기</a><span className="tech">{md(x.updated || x.created)}</span></div>
        <p className="ferr" role="alert" aria-atomic="true">{w.errOf(x.id)}</p>
      </article>
    ))}</div>
  );
}
