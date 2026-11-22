// 루틴판(2026-11-21) — 세 열 들어온 것 → 내가 정한 것 → 쓰는 중. 열마다 큰 숫자 하나 · 뜻 한 줄 · 다듬은 줄 3개(MM-DD 날짜 앞, 「외 N건」).
// 줄 = 대상 항목 탭(기록이면 기록 화면) 링크 · 쓰는 중 카드 = 한판 상세(#_me/board/<id>) 링크. 버튼 0. 숫자·줄은 서버 /api/me/routine 그대로(다시 세지 않는다).
// 블록 아래 한 줄 = 지난 루틴 뒤 새로 생긴 것과 다듬을 것(셋 다 0 이면 숨김). 설정 p 가 없거나 오브젝트가 없으면 안내 한 줄만.
import { useQuery } from "@tanstack/react-query";
import { mmdd } from "../../../shared/date";
import { objFilterQuery, type ObjFilter } from "../../../shared/route";
import { meApi, type RoutineAxis, type RoutineCard, type RoutineLine } from "../meApi";
import { objHref } from "../obj/ObjTab";
import { Wait } from "./Wait";
import type { BlockProps } from "./block";
import css from "./Routine.module.css";

export const RT = {
  label: "루틴판", setup: "어떤 오브젝트를 열에 둘지 대화로 정하세요",
  in: "들어온 것", decided: "내가 정한 것", writing: "쓰는 중",
  inMean: (sig: number) => `이번 주 읽은 글, 그중 신호 ${sig}`, decidedMean: "결과를 아직 확인 안 한 결정", none: (n: number) => `판정 없음 ${n}`,
  writingMean: "이렇게 해야 한다로 정리 중", more: (n: number) => `외 ${n}건`,
  open: (n: number, mean: string) => `${n}, ${mean}. 목록 보기`, byAxis: "최근 7일 축별 수", axMore: (n: number) => `외 ${n}`,
  // 0 인 쪽은 빼고, 둘 다 0 이면 「출처 없음」
  cardMeta: (c: RoutineCard) => [c.n_posts ? `글 ${c.n_posts}` : "", c.n_records ? `결정 ${c.n_records}` : ""].filter(Boolean).join(", ") || "출처 없음",
  since: (n: number, m: number, k: number) => `지난 루틴 뒤 들어온 것 ${n}, 정한 것 ${m}. 다듬을 것 ${k}. 대화에서 '루틴 하자'`,
};
// 큰 숫자 → 그 오브젝트 탭 목록에 필터를 건 주소(2026-11-22). 들어온 것 = 최근 7일 · 내가 정한 것 = 판정 미확인 · 쓰는 중 = stage 칸 값
const str = (v: unknown) => (typeof v === "string" ? v.trim() : "");
const listHref = (key: string, F: Partial<ObjFilter>) => (key ? objHref(key) + objFilterQuery(F) : "");
export function bigHrefs(p: Record<string, unknown>) {
  const vf = str(p.verdict), [sf, sv] = str(p.stage).split(":").map(x => x.trim());
  return {
    in: listHref(str(p.in), { window: 7 }),
    decided: vf ? listHref(str(p.decided), { verdict: `${vf}:unknown` }) : "",
    writing: listHref(str(p.writing), sf && sv ? { f: { [sf]: sv } } : {}),
    axis: (id: string) => listHref(str(p.in), { window: 7, axis: id }),
  };
}
export const AXES_MAX = 5;
export const boardHref = (id: string) => `#_me/board/${encodeURIComponent(id)}`;
// 줄 대상 — 항목이 있으면 그 오브젝트 탭 항목 페이지, 기록뿐이면 기록 화면
export function lineHref(t: RoutineLine["target"]): string {
  const item = t.item_id || (t.kind === "item" ? t.id : "");
  if (item && t.object_key) return `#_me/obj/${encodeURIComponent(t.object_key)}/${encodeURIComponent(item)}`;
  return t.kind === "record" ? `#_me/journal/${encodeURIComponent(t.id)}` : "";
}

function Lines({ lines, more }: { lines: RoutineLine[]; more: number }) {
  return (
    <>
      <ul className={css.lines}>{lines.map((l, i) => {
        const href = lineHref(l.target), inner = <><span className={css.dt}>{mmdd(l.date)}</span><span className={css.lt}>{l.text}</span></>;
        return <li key={i}>{href ? <a className={css.ln} href={href}>{inner}</a> : <span className={css.ln}>{inner}</span>}</li>;
      })}</ul>
      {more > 0 ? <p className={css.more}>{RT.more(more)}</p> : null}
    </>
  );
}

// 숫자가 링크(href 있을 때) — 그 목록으로. 링크 이름 = 숫자 + 뜻
const Big = ({ n, mean, sub, href }: { n: number; mean: string; sub?: string; href?: string }) =>
  <p className={css.big}>{href ? <a className={css.bn} href={href} aria-label={RT.open(n, mean)}><b>{n}</b></a> : <b>{n}</b>}<span>{mean}</span>{sub ? <small>{sub}</small> : null}</p>;
// 들어온 것 축별 수 한 줄 — 많은 순 최대 5, 나머지 「외 N」(N = 축 수). 칩 = 최근 7일 + 그 축 목록
function ByAxis({ ax, href }: { ax: RoutineAxis[]; href: (id: string) => string }) {
  const top = [...ax].filter(a => a.n > 0).sort((x, y) => y.n - x.n), shown = top.slice(0, AXES_MAX);
  if (!shown.length) return null;
  return (
    <p className={css.ax} id="rt-axes" aria-label={RT.byAxis}>{shown.map(a => {
      const h = href(a.item_id), inner = <><b>{a.code || a.title}</b><span>{a.n}</span></>;
      return h ? <a key={a.item_id} className={css.axc} href={h} title={a.title || ""}>{inner}</a> : <span key={a.item_id} className={css.axc}>{inner}</span>;
    })}{top.length > AXES_MAX ? <span className={css.axm}>{RT.axMore(top.length - AXES_MAX)}</span> : null}</p>
  );
}
const Arr = () => <div className={css.arr} aria-hidden="true"><span /></div>;

export function Routine({ W, p }: BlockProps) {
  const q = useQuery({ queryKey: ["me", "routine", W.S.generated || ""], queryFn: meApi.routine });
  const r = q.data;
  if (!r) return <section className={css.rt} id="routine" aria-label={RT.label}><Wait fail={q.isError} /></section>;
  if (!r.ready || (r.missing || []).length) return <section className={css.rt} id="routine" aria-label={RT.label}><p className="hint">{RT.setup}</p></section>;
  const n = r.since.new_in, m = r.since.new_decided, k = r.in.unrefined + r.decided.unrefined, H = bigHrefs(p || {});
  return (
    <section className={css.rt} id="routine" aria-label={RT.label}>
      <div className={css.flow}>
        <section className={css.col} id="rt-in"><h3>{RT.in}</h3>
          <Big n={r.in.n_7d} mean={RT.inMean(r.in.signal_7d)} href={H.in} />
          <ByAxis ax={r.in.by_axis || []} href={H.axis} />
          <Lines lines={r.in.lines} more={r.in.more} /></section>
        <Arr />
        <section className={css.col} id="rt-decided"><h3>{RT.decided}</h3>
          <Big n={r.decided.unknown} mean={RT.decidedMean} sub={RT.none(r.decided.none)} href={H.decided} />
          <Lines lines={r.decided.lines} more={r.decided.more} /></section>
        <Arr />
        <section className={css.col} id="rt-writing"><h3>{RT.writing}</h3>
          <Big n={r.writing.drafts} mean={RT.writingMean} href={H.writing} />
          <ul className={css.cards}>{r.writing.cards.map(c => (
            <li key={c.item_id}><a className={css.card} href={boardHref(c.item_id)}><span className={css.tt}>{c.key_line}</span><span className={css.tc}>{RT.cardMeta(c)}</span></a></li>
          ))}</ul></section>
      </div>
      {n + m + k > 0 ? <p className={css.since} id="rt-since">{RT.since(n, m, k)}</p> : null}
    </section>
  );
}
