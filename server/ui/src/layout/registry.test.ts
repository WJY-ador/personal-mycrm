// 요약 블록 레지스트리 — 정본 server/layout_registry.json(Python layout_check 와 같은 파일)의 컴포넌트 id = BLOCKS 키(빠짐·남음 0) ·
// 기본 배치의 블록은 전부 그릴 수 있다 · 「나」 하위 탭 기본 = 화면이 아는 7 탭.
import { expect, test } from "vitest";
import { BLOCKS, REGISTRY, SCREENS } from "./registry";
import { ME_TABS } from "../features/me/text";
import migrated from "../../migrated.json";

test("BLOCKS 키 = 레지스트리 컴포넌트 id · 블록은 summary 영역 · 기본 배치 그릴 수 있음", () => {
  expect(Object.keys(BLOCKS).sort()).toEqual(Object.keys(REGISTRY.components).sort());
  for (const c of Object.values(REGISTRY.components)) expect(c.regions).toContain("summary");
  const def = REGISTRY.pages.me.default;
  expect(def.regions.summary.every(s => s.c in BLOCKS)).toBe(true);
  expect([...def.tabs].sort()).toEqual([...ME_TABS].sort());
  expect(Object.keys(SCREENS).sort()).toEqual(Object.keys(migrated.screens).sort());   // 옮긴 화면 = 래칫 목록(server/ui/migrated.json)
});
