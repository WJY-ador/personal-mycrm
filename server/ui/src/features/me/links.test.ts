// 연결 상한·라벨 — 넓은 화면 25노드·40연결 · 1열 12·18(중심 포함) · 넘치면 생략 수 + 종류 거르기 · 라벨 2줄(12자·8자)
import { expect, test } from "vitest";
import { capped, lines, type Edge } from "./links";

const e = (i: number, kind = "item"): Edge => ({ node: { key: `${kind}:${i}`, kind, id: String(i), label: `노드 ${i}`, kindName: kind, href: "", lazy: false }, rel: "r", dir: "in" });

test("상한 — 넓은 화면 노드 24(+중심) · 1열 11 · 생략 수 · 종류 거르기는 넘칠 때만", () => {
  const all = [...Array.from({ length: 30 }, (_, i) => e(i)), e(99, "journal")];
  const w = capped(all, false, "");
  expect([w.nodes.length, w.edges.length, w.omitN, w.omitE, w.filter]).toEqual([24, 24, 7, 7, true]);
  const n = capped(all, true, "");
  expect([n.nodes.length, n.omitN]).toEqual([11, 20]);
  const k = capped(all, false, "journal");
  expect(k.nodes.map(x => x.key)).toEqual(["journal:99"]);
  expect(capped(all.slice(0, 3), false, "").filter).toBe(false);
});

test("라벨 = 2줄, 띄어쓰기에서 끊고 넘치면 말줄임", () => {
  expect(lines("짧은 이름", false)).toEqual(["짧은 이름"]);
  expect(lines("담당이 먼저 도구는 그다음이다", false)).toEqual(["담당이 먼저 도구는", "그다음이다"]);
  expect(lines("가".repeat(30), true)).toEqual(["가".repeat(8), "가".repeat(7) + "…"]);
});
