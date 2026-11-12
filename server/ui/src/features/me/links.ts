// 연결(순수 함수) — 중심 하나의 직접 이웃(저장된 관계만). 옛 app.html graphNode·graphEdges·graphLines·meN·mePick 그대로.
// 이웃 순서 = 자료 종류 고정 순서 → 안정 식별자(이름을 고쳐도 자리가 안 바뀐다). 상한 넓은 화면 25노드·40연결, 1열 12·18(중심 포함).
import { dOnly } from "../../shared/date";
import { axes, defById, itemById, qById, records, srcById, type TabRow, type World } from "./model";
import { firstLine, type MeTab } from "./text";

export type GNode = { key: string; kind: string; id: string; label: string; kindName: string; href: string; lazy: boolean };
export type Edge = { node: GNode; rel: string; dir: "out" | "in" };

const ORDER = ["journal", "q", "cand", "item", "refl", "person", "source", "activity"];
export const CAP = { wide: [25, 40], narrow: [12, 18] } as const;
const RECLINK_LABEL: Record<string, string> = { attach_to: "붙는 곳", axes: "축" };
const LINK_KIND: Record<string, string> = { record: "journal", candidate: "cand", item: "item", person: "person", source: "source", activity: "activity" };
const KIND_NAME: Record<string, string> = { journal: "내 글", q: "질문", refl: "읽고 든 생각", person: "사람", source: "출처", activity: "활동" };
const CAND_NAME: Record<string, string> = { pending: "검토할 판단", confirmed: "확정한 판단", excluded: "반영 안 한 판단" };

function find(W: World, kind: string, id: string) {
  const S = W.S;
  if (kind === "journal") return records(W).find(r => r.id === id);
  if (kind === "q") return qById(W, id);
  if (kind === "cand") return (S.candidates || []).find(c => c.id === id);
  if (kind === "item") return itemById(W, id);
  if (kind === "refl") return (S.reflections || []).find(x => x.id === id);
  if (kind === "person") return (S.people || []).find(p => p.id === id);
  if (kind === "source") return srcById(W, id);
  return undefined;
}

export function kindName(W: World | null, kind: string, id = ""): string {
  const x = W && id ? find(W, kind, id) : undefined;
  if (kind === "cand") return x && "status" in x ? CAND_NAME[String(x.status)] || "판단" : "판단";
  if (kind === "item") return x && "object_id" in x ? defById(W!, String(x.object_id))?.label || "항목" : "항목";
  return KIND_NAME[kind] || kind;
}

export const actName = (W: World, a: { action: string; action_label?: string; occurred_on: string | null }) =>
  `${a.action_label || W.S.activity_ui?.actions?.[a.action] || a.action}, ${a.occurred_on ? dOnly(a.occurred_on) : "날짜 미확인"}`;

// 노드 — lazy = 이름을 따로 받아야 하는 노드(이어 받지 않은 기록·문맥 API 밖 활동)
export function node(W: World, kind: string, id: string): GNode {
  const S = W.S;
  let label = "", href = "", lazy = false;
  if (kind === "journal") { const x = records(W).find(r => r.id === id); label = x ? x.title || x.excerpt || "(제목 없음)" : ""; href = `#_me/journal/${id}`; lazy = !x; }
  else if (kind === "q") { label = qById(W, id)?.text || ""; href = `#_me/q/${id}`; }
  else if (kind === "cand") { const x = (S.candidates || []).find(c => c.id === id); label = x?.text || "";
    href = x && (x.status === "pending" || x.status === "confirmed") ? `#_me/cand/${id}` : x ? `#structure/cand/${x.status}` : ""; }
  else if (kind === "item") { const x = itemById(W, id); label = x ? (x.code ? x.code + " " : "") + (x.title || "(제목 없음)") : "";
    href = x && x.revision ? `#_me/item/${id}` : x ? `#structure/${x.object_id}/${id}` : ""; }
  else if (kind === "refl") { label = firstLine((S.reflections || []).find(x => x.id === id)?.body); href = `#_me/refl/${id}`; }
  else if (kind === "person") { label = (S.people || []).find(p => p.id === id)?.alias || ""; href = `#_obj/person/${id}`; }
  else if (kind === "source") { label = srcById(W, id)?.name || ""; href = `#_obj/source/${id}`; }
  else if (kind === "activity") { href = `#_obj/activity/${id}`; const a = W.acts[id]; if (a) label = actName(W, a); else lazy = true; }
  return { key: `${kind}:${id}`, kind, id, label: label || kindName(W, kind, id), kindName: kindName(W, kind, id), href, lazy };
}

const fieldLabel = (W: World, objectId: string, key: string) => defById(W, objectId)?.fields?.find(f => f.key === key)?.label || key;

// 중심 하나의 직접 연결 — 같은 이웃이 여러 관계로 이어지면 연결은 여러 개, 노드는 하나
export function edges(W: World, kind: string, id: string): Edge[] {
  const S = W.S, out: Edge[] = [];
  const add = (k: string | undefined, i: string | null | undefined, rel: string, dir: "out" | "in") => {
    if (k && i && !(k === kind && i === id)) out.push({ node: node(W, k, i), rel, dir }); };
  const c = kind === "cand" ? (S.candidates || []).find(x => x.id === id) : undefined;
  const r = kind === "journal" ? records(W).find(x => x.id === id) : undefined;
  const f = kind === "refl" ? (S.reflections || []).find(x => x.id === id) : undefined;
  const it = kind === "item" ? itemById(W, id) : undefined;
  if (c) { add("journal", c.record_id, "근거", "out"); add("q", c.question_id, "질문", "out"); }
  if (r) { add("q", r.question_id, "질문", "out"); add("source", r.source_id, "출처", "out"); }
  if (f) add("source", f.source_id, "출처", "out");
  if (it) for (const l of it.links || []) add(LINK_KIND[l.target_kind], l.target_id, fieldLabel(W, it.object_id, l.field_key), "out");
  if (kind === "journal") for (const l of S.record_links || []) if (l.record_id === id) add(LINK_KIND[l.target_kind], l.target_id, RECLINK_LABEL[l.field_key] || l.field_key, "out");
  const target = ({ journal: "record", cand: "candidate", item: "item" } as Record<string, string>)[kind];
  if (target) for (const it of S.items || []) for (const l of it.links || [])
    if (l.target_kind === target && l.target_id === id) add("item", it.id, fieldLabel(W, it.object_id, l.field_key), "in");
  if (kind === "item" || kind === "cand") for (const l of S.record_links || [])
    if (l.target_kind === target && l.target_id === id) add("journal", l.record_id, RECLINK_LABEL[l.field_key] || l.field_key, "in");
  if (kind === "journal") for (const c of S.candidates || []) if (c.record_id === id) add("cand", c.id, "근거", "in");
  if (kind === "q") {
    for (const c of S.candidates || []) if (c.question_id === id) add("cand", c.id, "질문", "in");
    for (const r of records(W)) if (r.question_id === id) add("journal", r.id, "질문", "in");
  }
  if (kind === "item") for (const a of W.axisCtx[id]?.activities || []) add("activity", a.id, "축", "in");
  const pc = kind === "person" ? W.personCtx[id] : null;
  if (pc) {
    for (const a of pc.activities) add("activity", a.id, "사람", "in");
    for (const r of pc.records) add("journal", r.id, "사람", "in");
    for (const i of pc.items) add("item", i.id, fieldLabel(W, i.object_id, i.field_key), "in");
  }
  const rank = (e: Edge) => ORDER.indexOf(e.node.kind);
  return out.sort((a, b) => rank(a) - rank(b) || (a.node.id < b.node.id ? -1 : a.node.id > b.node.id ? 1 : 0) || (a.dir < b.dir ? -1 : 1));
}

// 그릴 몫 — 상한·종류 거르기. hidden = 받은 목록 밖 활동 수(서버가 센 수 − 받은 수)도 생략에 넣는다
export function capped(all: Edge[], narrow: boolean, kind: string, hidden = 0) {
  const [maxN, maxE] = narrow ? CAP.narrow : CAP.wide;
  const kinds = [...new Set(all.map(e => e.node.kind))];
  const k = kinds.includes(kind) ? kind : "";
  const nodes: GNode[] = [], shown: Edge[] = [], seen = new Set<string>();
  for (const e of k ? all.filter(x => x.node.kind === k) : all) {
    if (!seen.has(e.node.key)) { if (nodes.length >= maxN - 1) continue; seen.add(e.node.key); nodes.push(e.node); }
    if (shown.length < maxE && seen.has(e.node.key)) shown.push(e);
  }
  const omitN = new Set(all.map(e => e.node.key)).size - nodes.length + hidden, omitE = all.length - shown.length + hidden;
  return { nodes, edges: shown, omitN, omitE, kinds, kind: k, filter: (omitN > 0 || omitE > 0 || !!k) && kinds.length > 1 };
}

const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
// 라벨 2줄 — 넓은 화면 12자·1열 8자씩, 넘치면 말줄임. 띄어쓰기에서 끊을 수 있으면 거기서
export function lines(label: string, narrow: boolean): string[] {
  const per = narrow ? 8 : 12, t = clip(String(label || ""), per * 2);
  if (t.length <= per) return [t];
  const sp = t.lastIndexOf(" ", per);
  const cut = sp > per / 2 && t.length - sp - 1 <= per ? sp : per;
  return [t.slice(0, cut).trim(), clip(t.slice(cut).trim(), per)];
}

// 한 행의 연결 수(목록 숫자 · 연결 최다 진입) — 축 = 통계 n, 사람 = 문맥 API(열어 봐야 안다), 출처 = 글 + 읽고 든 생각
export function rowN(W: World, tab: MeTab, id: string): number | null {
  if (tab === "axis") { const a = axes(W).find(x => x.id === id); return a ? a.n : null; }
  if (tab === "source") return (W.S.source_counts?.by_source?.[id] || 0) + (W.S.reflections || []).filter(x => x.source_id === id).length;
  if (tab === "person") { const c = W.personCtx[id]; return c ? c.activity_count + c.records.length + c.items.length : null; }
  return new Set(edges(W, "item", id).map(e => e.node.key)).size;
}

// 진입 — 주소의 id 가 그 탭에 있으면 그것, 없으면 연결 최다(같으면 앞 행)
export function pick(W: World, tab: MeTab, rows: TabRow[], want: string): TabRow | null {
  if (want) return rows.find(r => r.id === want) || null;
  let best: TabRow | null = null, bn = -1;
  for (const r of rows) { const n = rowN(W, tab, r.id) || 0; if (n > bn) { best = r; bn = n; } }
  return best;
}
