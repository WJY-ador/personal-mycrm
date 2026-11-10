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
      const at = resolve(p, spec);
      seen++;
      // src 밖은 하나만 — 요약 블록 레지스트리 정본(server/layout_registry.json, Python 과 같은 파일)을 layout 이 읽는다
      if (!at.startsWith("./")) { if (!(from === "layout" && spec === "../../../layout_registry.json")) bad.push(`${p} → ${spec}`); continue; }
      const to = area(at);
      if (to === from) continue;
      const ok =
        (from === "main.tsx" && (to === "layout" || to === "shared")) ||
        (from === "layout" && (to.startsWith("features/") || to === "shared")) ||
        (from.startsWith("features/") && to === "shared") ||
        from === "test";   // 시험 도우미(src/test — 화면이 import 하지 않는다, 아래 검사) 는 어디든 띄워 본다
      if (!ok) bad.push(`${p} → ${spec}`);
    }
  }
  expect(bad).toEqual([]);
  const toTest = Object.entries(files).filter(([p, src]) => area(p) !== "test" && imports(src).some(s => s.startsWith(".") && area(resolve(p, s)) === "test")).map(([p]) => p);
  expect(toTest).toEqual([]);   // 화면 코드는 시험 도우미를 쓰지 않는다
  expect(Object.keys(files)).toContain("./main.tsx");
  expect(seen).toBeGreaterThan(10);   // 빈 검사 방지 — 실제 import 를 읽었다
});

test("src 에 innerHTML·dangerouslySetInnerHTML 0", () => {
  const hits = Object.entries(all).filter(([p, s]) => p !== "./arch.test.ts" && /innerHTML|dangerouslySetInnerHTML/.test(s)).map(([p]) => p);
  expect(hits).toEqual([]);
});

// 토큰·이관 본문은 저장하지 않는다(옛 test_web_import·test_migration_screen 정적 절) — 브라우저 저장소 쓰기 = 원문 보기 포트 · PC 앱 새 버전 나중에 기록 둘 ·
// sessionStorage·console 0 · 이관 토큰 경로(/api/migration/ — PC 업로더 몫)는 화면이 부르지 않는다 · 원문 = 127.0.0.1 링크 한 곳(fetch 0)
test("저장소 쓰기 = 원문 포트·앱 업데이트 나중에 둘 · console·sessionStorage 0 · 이관 토큰 경로 0 · 127.0.0.1 = 링크 한 곳", () => {
  const src = Object.entries(files);
  expect(src.flatMap(([p, s]) => [...s.matchAll(/localStorage\.setItem\(([^,]+),/g)].map(m => `${p}:${m[1]}`))).toEqual(["./features/activity/RawBox.tsx:RAW_PORT_KEY", "./shared/desktopUpdate.ts:DISMISS_KEY"]);   // + PC 앱 새 버전 띠 나중에 기록(버전·시각)
  expect(src.filter(([, s]) => /sessionStorage|console\.|\/api\/migration\//.test(s)).map(([p]) => p)).toEqual([]);
  expect(src.filter(([, s]) => s.includes("127.0.0.1")).map(([p]) => p)).toEqual(["./features/activity/RawBox.tsx"]);
  expect(src.filter(([, s]) => /fetch\([^)]*127\.0\.0\.1/.test(s))).toEqual([]);
});
