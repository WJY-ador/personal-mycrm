// 사례 짝 짓기(구현계획 3절) — 짝 맞음, 안 맞는 사례 남김, 라벨 표, 원문 보존. 문장은 모두 가짜.
import { expect, test } from "vitest";
import { pairCases, type Seg } from "./cases";

const DOC = [
  "머리 문단이에요.",
  "",
  "## 순서를 먼저 정한다",
  "",
  "본문 한 단락.",
  "",
  "## 입력은 한 곳",
  "",
  "본문 둘.",
  "",
  "## 사례로 다시 보기",
  "",
  "### 순서를 먼저 정한다",
  "",
  "**그때 상황** 도구가 셋이었다.",
  "",
  "**바꾼 것과 포기한 것**: 하나로 줄였다.",
  "둘째 줄도 이어진다.",
  "",
  "**관측한 결과** 한 주 뒤 입력이 늘었다.",
  "",
  "**남은 기준** 도구보다 순서.",
  "",
  "덧붙인 문단.",
  "",
  "### 위에 없는 제목",
  "",
  "**그때 상황** 짝이 없다.",
  "",
].join("\n");

const md = (s: Seg[]) => s.filter(x => x.k === "md").map(x => (x as { text: string }).text).join("\n");

test("짝 맞는 사례 = 위 절 끝으로, 라벨 네 문단 = 표 줄", () => {
  const s = pairCases(DOC);
  const i = s.findIndex(x => x.k === "cases");
  expect((s[i - 1] as { text: string }).text).toBe("## 순서를 먼저 정한다\n\n본문 한 단락.");
  const c = (s[i] as { items: { title: string; rows: { label: string; text: string }[]; rest: string }[] }).items;
  expect(c.map(x => x.title)).toEqual(["순서를 먼저 정한다"]);
  expect(c[0].rows).toEqual([
    { label: "그때 상황", text: "도구가 셋이었다." },
    { label: "바꾼 것과 포기한 것", text: "하나로 줄였다.\n둘째 줄도 이어진다." },
    { label: "관측한 결과", text: "한 주 뒤 입력이 늘었다." },
    { label: "남은 기준", text: "도구보다 순서." },
  ]);
  expect(c[0].rest).toBe("덧붙인 문단.");
});

test("안 맞는 사례 = 사례 절에 그대로, 절 제목 남김", () => {
  const t = md(pairCases(DOC));
  expect(t).toContain("## 사례로 다시 보기\n\n### 위에 없는 제목\n\n**그때 상황** 짝이 없다.");
  expect(t).not.toContain("### 순서를 먼저 정한다");
});

test("모두 옮겨지면 사례 절 제목도 그리지 않는다", () => {
  const only = DOC.split("### 위에 없는 제목")[0];
  const s = pairCases(only);
  expect(md(s)).not.toContain(CASES_TXT);
  expect(s.filter(x => x.k === "cases")).toHaveLength(1);
});
const CASES_TXT = "사례로 다시 보기";

test("사례 절이 없거나 울타리 안 제목 = 글 그대로", () => {
  const plain = "## 하나\n\n본문.";
  expect(pairCases(plain)).toEqual([{ k: "md", text: plain }]);
  const fenced = "## 하나\n\n```\n## 사례로 다시 보기\n### 하나\n```";
  expect(pairCases(fenced)).toEqual([{ k: "md", text: fenced }]);
});

test("원문 보존 — 입력의 빈 줄 아닌 줄이 모두 결과에 있다(옮긴 사례 제목 줄, 빠진 절 제목 줄 빼고)", () => {
  const s = pairCases(DOC);
  const out = s.flatMap(x => x.k === "md" ? x.text.split("\n") : x.items.flatMap(c => [...c.rows.flatMap(r => [`**${r.label}**`, ...r.text.split("\n")]), ...c.rest.split("\n")]));
  const joined = out.join("\n");
  for (const l of DOC.split("\n").filter(l => l.trim() && l !== "### 순서를 먼저 정한다")) {
    const body = l.replace(/^\*\*[^*]+\*\*:?\s*/, "");
    expect(joined).toContain(body);
  }
});
