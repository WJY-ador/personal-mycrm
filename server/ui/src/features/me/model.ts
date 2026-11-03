// 「나」 자료 규칙(순수 함수) — 옛 app.html homeRows·meRows·meAxes·meN·mePick·meTabOfItem 그대로. 연결 = 저장된 관계만(추정 0).
// W = 화면이 지금 가진 것: 상태 S + 이어 받은 기록 + 통계 + 문맥 API 결과(축·사람 — 이 화면에 머무는 동안).
import { timeOf } from "../../shared/date";
import { meTabOf } from "../../shared/route";
import { srcText as srcTextOf } from "../../shared/source";
import { readOk, type AppState, type Cand, type Def, type Item, type Person, type Question, type Rec, type Refl, type Source } from "../../shared/state";
import type { Act, AxisCtx, PersonCtx, Stats } from "./meApi";
import { ME_STD, REFL_KIND, SRC_KIND, firstLine, type MeTab } from "./text";

export type World = {
  S: AppState; recs: Rec[]; stats: Stats | null;
  axisCtx: Record<string, AxisCtx | null>;     // null = 못 받음
  personCtx: Record<string, PersonCtx | null>;
  acts: Record<string, Act>;                   // 문맥 API 가 준 활동(행동·날짜·사람)
};
type Head = { id: string; title: string; kind: string; at: string };
export type Row = Head & ({ k: "journal"; x: Rec } | { k: "q"; x: Question } | { k: "cand"; x: Cand } | { k: "item"; x: Item } | { k: "refl"; x: Refl });
export type TabRow = { id: string; title: string; code: string | null; meta: string; grp?: string; x: Item | Person | Source };

export const defs = (W: World) => (W.S.definitions || []).filter(d => !d.archived_at);
export const defById = (W: World, id: string) => (W.S.definitions || []).find(d => d.id === id);
export const objLabel = (W: World, id: string) => defById(W, id)?.label || "항목";
export const itemById = (W: World, id: string) => (W.S.items || []).concat(W.S.item_proposals || []).find(it => it.id === id);
export const qById = (W: World, id: string) => (W.S.questions || []).find(q => q.id === id);
export const srcById = (W: World, id: string | null) => (W.S.sources || []).find(x => x.id === id);
export const srcText = (W: World, sid: string | null) => srcTextOf(W.S.sources, sid);
export const srcName = (W: World, sid: string) => { const x = srcById(W, sid); return x ? `${x.name} · ${SRC_KIND[x.kind] || x.kind}` : "찾을 수 없는 출처"; };
export const records = (W: World) => (readOk(W.S, "journal") ? W.recs : []);

export const stdDef = (W: World, tab: string): Def | undefined => defs(W).find(d => d.std_id === ME_STD[tab]);
export const customDefs = (W: World) => defs(W).filter(d => !Object.values(ME_STD).includes(d.std_id || ""));
export const itemsOf = (W: World, defId: string) => (W.S.items || []).filter(it => it.object_id === defId);
const codeCmp = (a: Item, b: Item) => (a.code ? 0 : 1) - (b.code ? 0 : 1) || String(a.code || "").localeCompare(String(b.code || ""), "ko", { numeric: true });
export const sorted = (xs: Item[]) => xs.map((x, i) => [x, i] as const).sort((p, q) => codeCmp(p[0], q[0]) || p[1] - q[1]).map(p => p[0]);

export const tabOfItem = (W: World, it: Item): MeTab => meTabOf(W.S, it);   // 판정 한 벌 = shared/route(옛 주소 replace 와 같은 규칙)

// 상세로 열 수 있는 데이터 — 만든 시각 최신 순(같으면 넣은 순)
export function homeRows(W: World): Row[] {
  const S = W.S, out: Row[] = [];
  for (const r of records(W)) out.push({ k: "journal", id: r.id, title: r.title || r.excerpt || "(제목 없음)", kind: "내 글", at: r.created, x: r });
  if (readOk(S, "questions")) for (const q of S.questions || []) out.push({ k: "q", id: q.id, title: q.text, kind: "질문", at: q.created, x: q });
  if (readOk(S, "candidates")) for (const c of S.candidates || []) {
    if (c.status === "pending") out.push({ k: "cand", id: c.id, title: c.text, kind: "검토할 판단", at: c.created, x: c });
    else if (c.status === "confirmed") out.push({ k: "cand", id: c.id, title: c.text, kind: "확정한 판단", at: c.created, x: c });
  }
  if (readOk(S, "items")) for (const it of S.items || []) out.push({ k: "item", id: it.id, title: it.title || "(제목 없음)", kind: objLabel(W, it.object_id), at: it.created_at, x: it });
  if (readOk(S, "reflections")) for (const x of S.reflections || []) out.push({ k: "refl", id: x.id, title: firstLine(x.body) || "(내용 없음)",
    kind: `읽고 든 생각 · ${REFL_KIND[x.kind] || x.kind}`, at: x.created, x });
  return out.map((r, i) => [r, i] as const).sort((a, b) => timeOf(b[0].at) - timeOf(a[0].at) || a[1] - b[1]).map(p => p[0]);
}

export function tabRows(W: World, tab: MeTab): TabRow[] {
  if (tab === "person") return (W.S.people || []).map(p => ({ id: p.id, title: p.alias, code: "", meta: "", x: p }));
  if (tab === "source") return (W.S.sources || []).map(s => ({ id: s.id, title: s.name, code: "", meta: SRC_KIND[s.kind] || s.kind, x: s }));
  if (tab === "custom") return customDefs(W).flatMap(d => sorted(itemsOf(W, d.id)).map(it => ({ id: it.id, title: it.title || "(제목 없음)", code: it.code, meta: d.label, grp: d.id, x: it })));
  const d = stdDef(W, tab);
  return d ? sorted(itemsOf(W, d.id)).map(it => ({ id: it.id, title: it.title || "(제목 없음)", code: it.code,
    meta: tab === "principle" ? (it.decision === "confirmed" ? "확정" : it.decision === "excluded" ? "반영 안 함" : "확정 전") : "", x: it })) : [];
}

// 하위 탭 건수 — 그 종류 전체(못 읽은 종류는 null = 숫자 없음)
export function tabCount(W: World, t: MeTab): number | null {
  const S = W.S;
  if (t === "summary") return null;
  if (t === "person") return Array.isArray(S.people) ? S.people.length : null;
  if (t === "source") return Array.isArray(S.sources) ? S.sources.length : null;
  if (!readOk(S, "items") || !Array.isArray(S.items)) return null;
  if (t === "custom") return customDefs(W).reduce((s, d) => s + itemsOf(W, d.id).length, 0);
  const d = stdDef(W, t);
  return d ? itemsOf(W, d.id).length : 0;
}

// 축 = 축 항목(코드 순 — 색 배정 고정) + 서버 통계 건수(id 로 맞춘다, 못 받으면 null)
export function axes(W: World) {
  const ax = stdDef(W, "axis"), by = Object.fromEntries((W.stats?.axes || []).map(a => [a.id, a]));
  return ax ? sorted(itemsOf(W, ax.id)).map(it => { const a = by[it.id];
    return { id: it.id, code: it.code, title: it.title || "", items: a?.items ?? null, records: a?.records ?? null, readings: a?.readings ?? null, n: a ? a.n : null }; }) : [];
}
export type Axis = ReturnType<typeof axes>[number];
export const AX_COLORS = 8;   // 축 색 = 코드 순 1~8, 9번째부터 회색(건수와 무관하게 고정)
export const axColor = (i: number) => (i < AX_COLORS ? `var(--ax${i + 1})` : "var(--soft)");
export const axShort = (t: string) => String(t || "").replace(/\s*\(.*\)\s*$/, "").replace(/\s+—\s+.*$/, "");
export const axTip = (a: Axis) => `${a.code ? a.code + " " : ""}${axShort(a.title)}${a.n === null ? "" : ` · 항목 ${a.items} · 글 ${a.records} · 읽기 자료 ${a.readings || 0}`}`;
