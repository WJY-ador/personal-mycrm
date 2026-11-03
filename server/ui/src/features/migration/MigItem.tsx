// 확인 화면 항목 한 줄(옛 migItemRow·migBodyHtml) — 번호·자료군·제목·action 칩·사유 · 기준 체크 상자(하나씩) · [본문 보기](펼칠 때 하나씩 받음)
import { rich } from "../../shared/rich";
import type { ItemBody, PItem } from "./migApi";
import { ActChip, Why } from "./Why";
import css from "./Migration.module.css";

export type BodyState = ItemBody | { error: string } | undefined;
type Props = { x: PItem; sealed: boolean; on: boolean; busy: boolean; open: boolean; body: BodyState; onCheck: (x: PItem, v: boolean) => void; onBody: (x: PItem) => void };

function Body({ b }: { b: BodyState }) {
  if (!b) return <p className="hint">불러오는 중이에요…</p>;
  if ("error" in b) return <p className="ferr">{b.error}</p>;
  const p = b.payload;
  if (!p) return <p className="hint">본문은 지웠어요(거절·반영·취소·만료 때 지워요).</p>;
  const kv = (k: string, v: React.ReactNode, has: unknown) => (has === undefined || has === null || has === "" ? null : <><dt>{k}</dt><dd>{v}</dd></>);
  const raw = <details className="tech"><summary>받은 그대로(JSON)</summary><pre className={css.json}>{JSON.stringify(p, null, 2)}</pre></details>;
  if (p.unit_kind === "source") {
    const s = p.source || { name: "", kind: "", location: "" };
    return <><dl className="kv">{kv("출처 이름", s.name, s.name)}{kv("종류", <code>{s.kind}</code>, s.kind)}{kv("위치(anchor 해시)", <code>{s.location}</code>, s.location)}</dl>{raw}</>;
  }
  const pd = p.primary_date ? <><code>{p.primary_date.kind}</code> {p.primary_date.value}</> : null;
  return (
    <>
      {p.title ? <p className={css.ttl}>{p.title}</p> : null}<div className="doc"><p className="pre">{rich(p.body || "")}</p></div>
      <dl className="kv">{kv("쓴 사람", <code>{p.author_kind}</code>, p.author_kind)}{kv("글 처리", <code>{p.text_process}</code>, p.text_process)}
        {kv("만든 방법", <code>{p.generation_kind}</code>, p.generation_kind)}{kv("날짜", pd, pd)}{kv("검토", <code>{p.review?.state}</code>, p.review?.state)}
        {kv("민감도", <code>{p.sensitivity}</code>, p.sensitivity)}</dl>{raw}
    </>
  );
}

export function MigItem({ x, sealed, on, busy, open, body, onCheck, onBody }: Props) {
  const title = x.title != null ? x.title || <span className="tech">(제목 없음)</span> : <span className="tech">(본문을 지웠어요)</span>;
  const check = x.needs_check && sealed && on
    ? <label className={css.chk}><input type="checkbox" data-seq={x.seq} checked={x.checked} disabled={busy} onChange={e => onCheck(x, e.target.checked)} /> 이 기준을 반영할게요</label>
    : x.needs_check ? <span className="tech">{x.checked ? "체크함" : "체크 안 함"}</span> : null;
  return (
    <li className={`${css.item}${x.needs_check && !x.checked ? " " + css.need : ""}`} id={`mig-i-${x.seq}`}>
      <div className={css.head}><span className="speclabel">#{x.seq}</span><code>{x.unit_kind}</code><b>{title}</b><ActChip a={x.action} /></div>
      {x.reason ? <span className="meta">사유 · <Why r={x.reason} /></span> : null}
      <div className="frow">{check}<button type="button" className="tertiary small" data-body={x.seq} aria-expanded={open} aria-controls={`mig-b-${x.seq}`} onClick={() => onBody(x)}>{open ? "본문 접기" : "본문 보기"}</button></div>
      {open ? <div className={css.body} id={`mig-b-${x.seq}`}><Body b={body} /></div> : null}
    </li>
  );
}
