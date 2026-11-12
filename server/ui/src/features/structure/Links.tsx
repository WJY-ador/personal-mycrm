// 서랍의 연결할 대상(옛 tgtHtml) — 참조 필드별 대상(제안이 가리키는 판단·글·항목). 대상이 지워졌으면 빈 자리 문구.
import { DecisionBadge } from "../../shared/CandChips";
import { md } from "../../shared/date";
import { press } from "../../shared/press";
import { recLabel } from "../../shared/RecDialog";
import { rich } from "../../shared/rich";
import type { AppState, Link } from "../../shared/state";
import type { ItemFull } from "./structApi";

type Open = (id: string, quote?: string) => void;
const go = (h: string) => () => { location.hash = h; };
const s = (v: unknown) => (v == null ? "" : String(v));

function Target({ S, it, l, open }: { S: AppState; it: ItemFull; l: Link; open: Open }) {
  const v = (it.targets || []).find(x => x.target_kind === l.target_kind && x.target_id === l.target_id)?.target;
  if (!v) return <span className="tech">근거를 이용할 수 없어요.</span>;   // 서버가 지운·휴지통 대상을 응답에서 뺀 빈 자리
  if (l.target_kind === "candidate")
    return <><div>{s(v.text)} <DecisionBadge status={s(v.status)} /></div>
      <div className="ev">근거 <a {...press(() => open(s(v.record_id), s(v.quote)))}>{recLabel(S, s(v.record_id))}</a>, <q><mark>{rich(s(v.quote))}</mark></q></div></>;
  if (l.target_kind === "record") return <><a {...press(() => open(s(v.id)))}>{s(v.title)}</a> <span className="tech">{md(s(v.created))}</span></>;
  return <><a {...press(go(`#structure/${s(v.object_id)}/${s(v.id)}`))}>{v.code ? <><span className="chip code">{s(v.code)}</span> </> : null}{s(v.title)}</a>{" "}
    <span className="tech">{s(v.object_label)}{v.archived_at ? ", 보관됨" : ""}</span></>;
}

export function Links({ S, it, cur, open }: { S: AppState; it: ItemFull; cur: Pick<ItemFull, "links">; open: Open }) {
  return (
    <>{it.fields.filter(f => f.value_type === "reference").map(f => {
      const ls = (cur.links || []).filter(l => l.field_key === f.key);
      return ls.length ? <div key={f.key}><h5>{f.label} <span className="count">{ls.length}</span></h5>
        <ul className="plist">{ls.map((l, i) => <li key={i}><Target S={S} it={it} l={l} open={open} /></li>)}</ul></div> : null;
    })}</>
  );
}
