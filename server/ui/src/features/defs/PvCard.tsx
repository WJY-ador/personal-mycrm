// 표준 하나(옛 pvCard) — 상태 · 내 자료 종류 · 구조 판정 · 뜻 확인 · 필요한 대상 · 잠금 영향 + [보류]·[거절]·[편입…](편입은 확인 대화창을 거친다).
import { BLOCK_TEXT, LOCK_TEXT, STD_CONFLICT, STD_READY, STD_STATE, STRUCT_TEXT } from "./text";
import type { PvObj } from "./stdApi";

type Props = { o: PvObj; all: PvObj[]; busy: boolean; st: string; er: string; choose: (o: PvObj, state: string) => void; ask: (o: PvObj) => void };

export function PvCard({ o, all, busy, st, er, choose, ask }: Props) {
  const stc = STD_STATE[o.state] || ["", o.state], obj = o.object, lock = o.lock || { changes: [], fields: [] };
  const nm = (k: string) => all.find(x => x.std_key === k)?.std_name || k;
  return (
    <article className="spvc" aria-labelledby={`spv-${o.std_key}`}><h4 id={`spv-${o.std_key}`}>표준 「{o.std_name}」<span className={`chip ${stc[0]}`.trim()}>{stc[1]}</span></h4>
      <dl><dt>내 자료 종류</dt><dd>{obj ? <>{obj.label} <span className="tech">{obj.key} · r{obj.revision}{obj.archived ? " · 보관됨" : ""}</span></> : "없음 — 편입하면 표준 정의를 새로 넣어요"}</dd>
        <dt>구조</dt><dd>{STRUCT_TEXT[o.structure] || o.structure}{(o.conflicts || []).length ? <ul>{o.conflicts.map((x, i) =>
          <li key={i}>{(STD_CONFLICT[x.code] || (() => "표준과 다른 곳이 있어요"))(x.field || "")}</li>)}</ul> : null}</dd>
        {o.meaning_check ? <><dt>뜻 확인</dt><dd>key 가 같아도 뜻이 같다는 보장은 없어요. 편입할 때 같은 뜻으로 쓰는지 확인해요.</dd></> : null}
        <dt>필요한 대상</dt><dd>{(o.needs || []).length ? <ul>{o.needs.map((n, i) => <li key={i}><span className="tech">{n.field}</span> → 표준 「{nm(n.std_key)}」 · {(STD_STATE[n.state] || ["", n.state])[1]}
          {n.ready ? "" : " — 먼저 편입해야 해요"}</li>)}</ul> : "없음"}</dd>
        <dt>잠금 영향</dt><dd><details><summary>편입하면 막히는 변경 {lock.changes.length}가지</summary><ul>{lock.changes.map(ch => <li key={ch}>{LOCK_TEXT[ch] || ch}</li>)}</ul>
          {lock.fields.length ? <>잠기는 표준 필드: <span className="tech">{lock.fields.join(", ")}</span></> : null}</details></dd></dl>
      {STD_READY.includes(o.state) ? <p className="hint" style={{ margin: ".5rem 0 0" }}>{BLOCK_TEXT.already}</p> : <>
        <div className="acts" role="group" aria-label={`표준 ${o.std_name} 선택`}>
          <button className="secondary" type="button" disabled={busy || o.state === "deferred"} onClick={() => choose(o, "deferred")}>보류</button>
          <button className="secondary" type="button" disabled={busy || o.state === "refused"} onClick={() => choose(o, "refused")}>거절</button>
          {o.can_incorporate ? <button className="primary" type="button" aria-haspopup="dialog" disabled={busy} onClick={() => ask(o)}>편입…</button> : null}</div>
        {o.can_incorporate ? null : <p className="blocked">편입할 수 없어요 — {(o.blocked || []).map(b => BLOCK_TEXT[b] || "지금은 편입할 수 없어요.").join(" ")}</p>}</>}
      <p className="pstatus" role="status" aria-atomic="true">{st}</p><p className="perror" role="alert" aria-atomic="true">{er}</p></article>
  );
}
