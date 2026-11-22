// 축 한 장의 「## 사례로 다시 보기」 짝 짓기(2026-11-22 구현계획 3절) — 그리기 전에만 바꾼다(저장 본문은 그대로, 결정적).
// 그 절 안 「### <제목>」 묶음을 위쪽 「## <같은 제목>」 절 끝으로 옮긴다(접힌 사례). 사례 안 네 라벨 문단은 라벨 | 내용 표 줄로.
// 제목이 위 절과 안 맞는 사례는 그 절에 그대로 남긴다(잃지 않게). 모두 옮겨지고 머리말도 없으면 그 절 제목도 그리지 않는다.
// 코드 울타리(```) 안의 「## 」·「### 」 줄은 제목으로 보지 않는다. 결과 = 조각 목록(md 글 | 사례 묶음) — 화면이 md() 와 표로 그린다.
export const CASES_HEAD = "사례로 다시 보기";
export const CASE_LABELS = ["그때 상황", "바꾼 것과 포기한 것", "관측한 결과", "남은 기준"] as const;

export type CaseRow = { label: string; text: string };
export type Case = { title: string; rows: CaseRow[]; rest: string };   // rest = 라벨 문단 밖의 글(md)
export type Seg = { k: "md"; text: string } | { k: "cases"; items: Case[] };

const SPLIT = /\r\n|\r|\n/;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const H2 = /^ {0,3}## +(.*?)(?: +#+)?\s*$/;
const H3 = /^ {0,3}### +(.*?)(?: +#+)?\s*$/;
const norm = (s: string) => s.replace(/\s+/g, " ").trim();
const LABEL = new RegExp(`^\\s*\\*\\*(${CASE_LABELS.join("|")})\\*\\*\\s*[:：\\-–—]?\\s*`);

type Sec = { head: string | null; title: string; lines: string[] };   // head = 「## 」 줄 원문(맨 앞 머리말은 null)

// 제목 줄마다 나눈다(울타리 안은 건너뜀). head 줄을 만나면 새 묶음
function cut(lines: string[], re: RegExp): Sec[] {
  const out: Sec[] = [{ head: null, title: "", lines: [] }];
  let fence = "";
  for (const l of lines) {
    const f = FENCE.exec(l);
    if (fence) { if (f && f[1][0] === fence[0] && f[1].length >= fence.length) fence = ""; }
    else if (f) fence = f[1];
    else { const m = re.exec(l); if (m) { out.push({ head: l, title: norm(m[1]), lines: [] }); continue; } }
    out[out.length - 1].lines.push(l);
  }
  return out;
}

const trimBlank = (ls: string[]) => {
  let a = 0, b = ls.length;
  while (a < b && !ls[a].trim()) a++;
  while (b > a && !ls[b - 1].trim()) b--;
  return ls.slice(a, b);
};

// 사례 본문 → 라벨 문단(표 줄) + 나머지 글. 문단 = 빈 줄로 나뉜 연속 줄
export function caseOf(title: string, lines: string[]): Case {
  const rows: CaseRow[] = [], rest: string[] = [];
  let para: string[] = [];
  const end = () => {
    if (!para.length) return;
    const m = LABEL.exec(para[0]);
    if (m) rows.push({ label: m[1], text: [para[0].slice(m[0].length), ...para.slice(1)].join("\n").trim() });
    else rest.push(para.join("\n"));
    para = [];
  };
  for (const l of lines) { if (l.trim()) para.push(l); else end(); }
  end();
  return { title, rows, rest: rest.join("\n\n") };
}

export function pairCases(text: string): Seg[] {
  const secs = cut(String(text || "").split(SPLIT), H2);
  const at = secs.findIndex(s => s.head !== null && s.title === CASES_HEAD);
  const md = (ls: string[]): Seg[] => { const t = trimBlank(ls); return t.length ? [{ k: "md", text: t.join("\n") }] : []; };
  if (at < 0) return md(secs.flatMap(s => (s.head === null ? s.lines : [s.head, ...s.lines])));
  const [intro, ...groups] = cut(secs[at].lines, H3);
  const moved = new Map<number, Case[]>(), left: Sec[] = [];
  for (const g of groups) {
    const to = secs.findIndex((s, i) => i < at && s.head !== null && s.title === g.title);
    if (to < 0) { left.push(g); continue; }
    moved.set(to, [...(moved.get(to) || []), caseOf(g.title, g.lines)]);
  }
  const out: Seg[] = [];
  secs.forEach((s, i) => {
    if (i === at) {
      const keep = trimBlank(intro.lines).length > 0 || left.length > 0;
      if (keep) out.push(...md([s.head!, ...intro.lines, ...left.flatMap(g => [g.head!, ...g.lines])]));
      return;
    }
    out.push(...md(s.head === null ? s.lines : [s.head, ...s.lines]));
    const cs = moved.get(i);
    if (cs) out.push({ k: "cases", items: cs });
  });
  return out;
}
