// 추천 초안 카드 하나 — 이름, 필드(어디서 뽑는지), 담을 규칙 문장, 견본 3건(제목 + 원문 인용), 채워질 건수 + [적용] [이름 고치기] [빼기].
// 담을 규칙이 없는 초안도 카드로 보이되 건수 줄은 없다. 견본 인용은 서버가 자른 원문 그대로 글자로만 그린다(서식 해석 없음).
import { useState } from "react";
import type { RecoDraft } from "./recoApi";
import { KIND_LABEL, RECO_TEXT as T } from "./text";

type Props = { d: RecoDraft; busy: boolean; st: string; er: string; apply: () => void; discard: () => void; rename: (label: string) => void };

export function RecoCard({ d, busy, st, er, apply, discard, rename }: Props) {
  const [naming, setNaming] = useState(false), [name, setName] = useState(d.label);
  const hid = `reco-${d.object_id}`;
  return (
    <article className="spvc" aria-labelledby={hid}>
      <h4 id={hid}>{d.label}<span className="tech">{d.key}</span>{d.semantic_kind ? <span className="chip">{KIND_LABEL[d.semantic_kind] || d.semantic_kind}</span> : null}
        {d.base_revision > 0 ? <span className="chip">{T.change}</span> : null}</h4>
      <dl><dt>{T.fields}</dt><dd>{d.fields.length ? d.fields.map(f => f.from ? `${f.label}(${f.from})` : f.label).join(", ") : T.noFields}</dd>
        <dt>{T.rule}</dt><dd>{d.rule || T.noRule}</dd>
        {d.samples.length ? <><dt>{T.samples}</dt><dd><ul>{d.samples.map((s, i) => <li key={i}><b>{s.title}</b>
          <blockquote className="reco-quote">{s.quote}</blockquote></li>)}</ul></dd></> : null}</dl>
      {d.has_route ? <p className="hint">{T.fill(d.would_fill, d.partial)}</p> : null}
      {naming ? <form className="reco-name" onSubmit={e => { e.preventDefault(); rename(name); setNaming(false); }}>
        <label>{T.newName} <input value={name} maxLength={200} onChange={e => setName(e.target.value)} autoFocus /></label>
        <div className="acts"><button className="primary" type="submit" disabled={busy || !name.trim() || name.trim() === d.label}>{T.save}</button>
          <button className="secondary" type="button" onClick={() => { setNaming(false); setName(d.label); }}>{T.cancel}</button></div></form>
        : <div className="acts" role="group" aria-label={`${d.label} 추천`}>
          <button className="primary" type="button" disabled={busy} onClick={apply}>{T.apply}</button>
          <button className="secondary" type="button" disabled={busy} onClick={() => setNaming(true)}>{T.rename}</button>
          <button className="secondary" type="button" disabled={busy} onClick={() => { if (window.confirm(T.discardAsk)) discard(); }}>{T.discard}</button></div>}
      <p className="pstatus" role="status" aria-atomic="true">{st}</p><p className="perror" role="alert" aria-atomic="true">{er}</p>
    </article>
  );
}
