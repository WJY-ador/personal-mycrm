// 구조 규약(구현계획 §2) — 「그 부분만 고친다」를 기계로 본다.
// .tsx 200줄 상한 · import 방향 layout → features → shared(features 끼리 금지, shared 는 위로 못 감) · innerHTML·dangerouslySetInnerHTML 0.
import { expect, test } from "vitest";

const files = import.meta.glob(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const all = import.meta.glob("./**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const area = (p: string) => (p.startsWith("./features/") ? `features/${p.split("/")[2]}` : p.split("/")[1]);
const imports = (src: string) => [...src.matchAll(/^\s*(?:import|export)\b[^"']*["']([^"']+)["']/gm)].map(m => m[1]);
function resolve(from: string, spec: string): string {
  const parts = from.split("/").slice(0, -1);
  for (const s of spec.split("/")) {
    if (s === "..") parts.pop();
    else if (s !== ".") parts.push(s);
  }
  return parts.join("/");
}

test("화면 파일(.tsx)은 200줄 이하", () => {
  const long = Object.entries(files).filter(([p, s]) => p.endsWith(".tsx") && s.split("\n").length > 200).map(([p]) => p);
  expect(long).toEqual([]);
});

test("import 방향 layout → features → shared, features 끼리 금지", () => {
  const bad: string[] = [];
  let seen = 0;
  for (const [p, src] of Object.entries(files)) {
    const from = area(p);
    for (const spec of imports(src).filter(s => s.startsWith("."))) {
      const to = area(resolve(p, spec));
      seen++;
      if (to === from) continue;
      const ok =
        (from === "main.tsx" && (to === "layout" || to === "shared")) ||
        (from === "layout" && (to.startsWith("features/") || to === "shared")) ||
        (from.startsWith("features/") && to === "shared");
      if (!ok) bad.push(`${p} → ${spec}`);
    }
  }
  expect(bad).toEqual([]);
  expect(Object.keys(files)).toContain("./main.tsx");
  expect(seen).toBeGreaterThan(10);   // 빈 검사 방지 — 실제 import 를 읽었다
});

test("src 에 innerHTML·dangerouslySetInnerHTML 0", () => {
  const hits = Object.entries(all).filter(([p, s]) => p !== "./arch.test.ts" && /innerHTML|dangerouslySetInnerHTML/.test(s)).map(([p]) => p);
  expect(hits).toEqual([]);
});
