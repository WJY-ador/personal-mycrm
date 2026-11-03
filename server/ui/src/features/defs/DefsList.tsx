// 구조 정의 목록(옛 renderDefs 목록 쪽) — S.structure(서버 contract.respond 본인 응답)만 그린다. origin·locked·cardinality 를 다시 판정하지 않는다.
// id dmo-o<n>·dmo-r<n>·dmo-core-<kind> = structure_svg node_anchor·rel_anchor·core_anchor(응답 순서 그대로) — 그래프 링크가 가리킨다.
import { OriginChip } from "../../shared/origin";
import type { AppState, StructObj, StructRel } from "../../shared/state";
import { CORE_LABEL, josa, KIND_LABEL, LOCK_TIP, VTYPE } from "./text";

const Lock = ({ on }: { on?: boolean }) => (on ? <span className="chip lock" title={LOCK_TIP}>표준 정의 보호</span> : null);

export function DefsList({ S, hit }: { S: AppState; hit: string }) {
  const st = S.structure, objs = st.objects, rels = st.relations || [], core = st.core || [];
  const oById = (id: string | null) => objs.find(o => o.id === id);
  const tgt = (r: StructRel) => r.target_kind === "item" ? oById(r.target_object_id)?.label || "찾을 수 없는 자료 종류" : CORE_LABEL[r.target_kind] || r.target_kind;
  const relOf = (oid: string, fk: string) => rels.find(r => r.object_id === oid && r.field_key === fk);
  const nItems = (id: string) => (S.items || []).filter(it => it.object_id === id).length;
  const h = (id: string) => (hit === id ? " dmo-hit" : "");
  const card = (o: StructObj, i: number) => (
    <article key={o.id} className={`sobj${o.locked ? " locked" : ""}${h(`dmo-o${i + 1}`)}`} id={`dmo-o${i + 1}`} tabIndex={-1} aria-labelledby={`sobj-${o.id}`}>
      <div className="sohead"><h3 id={`sobj-${o.id}`}>{o.label}</h3><span className="tech">{o.key}</span></div>
      <div className="labels"><OriginChip S={S} o={o.origin} /><Lock on={o.locked} />{o.std_name ? <span className="chip">표준 「{o.std_name}」</span> : null}
        <span className="chip">{KIND_LABEL[o.semantic_kind || ""] || o.semantic_kind}</span><span className="chip">항목 {nItems(o.id)}</span></div>
      {(o.fields || []).length ? <div className="sftbl-wrap"><table className="sftbl"><thead><tr><th scope="col">필드</th><th scope="col">key</th><th scope="col">값</th>
        <th scope="col">구분</th><th scope="col">보호</th></tr></thead><tbody>{(o.fields || []).map(f => {
          const r = f.value_type === "reference" ? relOf(o.id, f.key) : undefined;
          return <tr key={f.key}><td>{f.label}{f.std_name && f.std_name !== f.label ? <> <span className="tech">표준 「{f.std_name}」</span></> : null}</td>
            <td><span className="tech">{f.key}</span></td>
            <td>{VTYPE[f.value_type] || f.value_type}{r ? <> → {tgt(r)} <span className="chip">{r.cardinality}</span></> : null}</td>
            <td><OriginChip S={S} o={f.origin} /></td><td>{f.locked ? <Lock on /> : <span className="tech">—</span>}</td></tr>;
        })}</tbody></table></div> : <p className="hint">필드가 없어요.</p>}</article>
  );
  const last = core.length ? CORE_LABEL[core[core.length - 1].kind] || "" : "";
  return (
    <>
      <section className="sec"><h3>자료 종류<span className="count">{objs.length}</span></h3>
        {objs.length ? <div className="sdef">{objs.map(card)}</div> : <div className="empty">아직 자료 종류가 없어요.</div>}</section>
      <section className="sec"><h3>관계<span className="count">{rels.length}</span></h3>
        {rels.length ? <ul className="srel">{rels.map((r, i) => {
          const o = oById(r.object_id), f = (o?.fields || []).find(x => x.key === r.field_key);
          return <li key={i} id={`dmo-r${i + 1}`} tabIndex={-1} className={h(`dmo-r${i + 1}`).trim() || undefined}><b>{o?.label || ""}</b><span className="tech">{f?.label || r.field_key}</span> → <b>{tgt(r)}</b>
            {" "}<span className="chip">{r.cardinality}</span><OriginChip S={S} o={r.origin} /><Lock on={r.locked} /></li>;
        })}</ul> : <div className="empty">참조 필드가 없어요.</div>}
        {core.length ? <p className="hint" style={{ margin: ".6rem 0 0" }}><OriginChip S={S} o="core" /> 공통으로 쓰는 {core.map((x, i) => <span key={x.kind}>{i ? "·" : ""}
          <b id={`dmo-core-${x.kind}`} tabIndex={-1} className={h(`dmo-core-${x.kind}`).trim() || undefined}>{CORE_LABEL[x.kind] || x.kind}</b></span>)}{josa(last, "을", "를")} 가리키는 관계가 있어요.</p> : null}</section>
    </>
  );
}
