// 이관 영수증(옛 migReceiptHtml) — 결과별 개수 · 항목별 결과·대상 id · 저장된 본문 해시(stored_hash)와 올린 content_hash 대조
import { mdhm } from "../../shared/date";
import type { Detail, Receipt, RItem } from "./migApi";
import { MIG_RES, MIG_RESULTS } from "./text";
import { UnitTable } from "./UnitTable";
import { StateChip } from "./Why";
import css from "./Migration.module.css";

function Hash({ x }: { x: RItem }) {
  if (!x.target_id) return <span className="tech">—</span>;
  if (x.stored_hash && x.stored_hash === x.content_hash) return <span className="chip st-mine">일치</span>;
  if (x.stored_hash) return <span className="chip flag">다름</span>;
  return <span className="chip st-off">{x.target_state === "trashed" ? "휴지통에 있음" : x.target_state === "missing" ? "찾을 수 없음" : "확인 못 함"}</span>;
}

export function MigReceipt({ pl, r }: { pl: Detail; r: Receipt }) {
  const xs = r.items || [], res = r.counts?.results || {}, units = r.counts?.units || {};
  const live = xs.filter(x => x.target_id), same = live.filter(x => x.stored_hash && x.stored_hash === x.content_hash).length;
  const cols = MIG_RESULTS.filter(k => res[k] || Object.values(units).some(u => u[k]));
  return (
    <>
      <div className="eyebrow">이관 영수증</div><h2 className="title">{pl.source_instance} <StateChip st={pl.state} /></h2>
      <dl className="kv"><dt>반영한 시각</dt><dd>{mdhm(r.applied_at)}</dd><dt>import_batch_id</dt><dd><code>{r.import_batch_id}</code></dd>
        <dt>plan_hash</dt><dd><code>{r.plan_hash}</code></dd><dt>receipt_hash</dt><dd><code>{r.receipt_hash}</code></dd>
        <dt>본문 해시 대조</dt><dd>{same} / {live.length} 일치</dd></dl>
      <UnitTable caption="결과별 개수" cols={cols} label={MIG_RES} units={units} total={res} />
      <section className="sec"><h2 className="sh">항목 <span className="speclabel">{xs.length}개</span></h2>
        <div className={css.wrap}><table className={`${css.tbl} ${css.rcpt}`}><thead><tr><th scope="col">#</th><th scope="col">자료군</th><th scope="col">결과</th>
          <th scope="col">대상 id</th><th scope="col">본문 해시</th><th scope="col">original_id</th></tr></thead>
          <tbody>{xs.map(x => <tr key={x.seq}><td>{x.seq}</td><td><code>{x.unit_kind}</code></td><td>{MIG_RES[x.result] || x.result}</td>
            <td>{x.target_id ? <code>{x.target_id}</code> : <span className="tech">—</span>}</td><td><Hash x={x} /></td><td><code>{x.original_id}</code></td></tr>)}</tbody></table></div></section>
      <p className="hint">본문은 반영할 때 서버 스테이징에서 지웠어요. 해시 대조는 지금 저장된 본문을 다시 계산해 올린 content_hash 와 견줘요.</p>
    </>
  );
}
