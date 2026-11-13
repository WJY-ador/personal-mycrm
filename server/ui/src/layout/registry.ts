// #view 화면 목록 — features 를 import 하는 곳(layout). 화면마다 지연 불러오기(React.lazy — 진입 묶음에 화면 코드를 넣지 않는다).
// 상시 섬(대화 서랍·머리글 스펙트럼·표시 이름·문의 대화창)은 진입 묶음 — App.tsx 가 바로 띄운다(누르기 전에 떠 있어야 한다).
import { lazy, type ComponentType } from "react";
import type { ScreenProps } from "../shared/ctx";

type Mod = Record<string, unknown>;
type Screen = ComponentType<ScreenProps>;
const one = (load: () => Promise<Mod>, name: string) => async () => (await load())[name] as Screen;

// 화면 이름 → 불러오기(시험은 이것으로 먼저 받아 둔다) · SCREENS = 같은 불러오기의 React.lazy
export const LOADERS: Record<string, () => Promise<Screen>> = {
  trash: one(() => import("../features/trash/TrashScreen"), "TrashScreen"),
  review: one(() => import("../features/review/ReviewScreen"), "ReviewScreen"),
  migration: one(() => import("../features/migration/MigrationScreen"), "MigrationScreen"),
  pc: one(() => import("../features/pc/PcScreen"), "PcScreen"),                            // 설정 「이 PC」(앱 다리 한 줄 — 연결 장치 화면 대신)
  activity: one(() => import("../features/activity/ActivityScreen"), "ActivityScreen"),   // 활동 목록·하나·축 하나(args = [activity|axis, …])
  objects: one(() => import("../features/objects/ObjectsScreen"), "ObjectsScreen"),        // 자료 종류 색인·사람·출처·읽고 든 생각(args = [a, b, c])
  today: one(() => import("../features/today/TodayScreen"), "TodayScreen"),                // 오늘·저장 승인 대기(args = [today, a, b] | [inbox, 상태])
  sheet: one(() => import("../features/sheet/SheetScreen"), "SheetScreen"),                // 질문·기록 탭(args = [탭 id, question|record, 조각, 고른 id])
  structure: one(() => import("../features/structure/StructureScreen"), "StructureScreen"),// 구조 항목·판단 문장 카드 + 항목 서랍(args = [a, b])
  defs: one(() => import("../features/defs/DefsScreen"), "DefsScreen"),                    // 내 구조 설정(목록·그래프·이름 공유·표준 편입)
  map: one(() => import("../features/map/MapScreen"), "MapScreen"),                        // 지도 칸반(args = [대조 경로 탭 id])
  name: one(() => import("../features/name/NameGate"), "NameGate"),                        // 이름 관문(표시 이름 없을 때)
  help: one(() => import("../features/desk/HelpScreen"), "HelpScreen"),                    // 설정 「문의 및 개인정보」
  me: one(() => import("./meEntry"), "Me"),
  layout: one(() => import("./meEntry"), "Layout"),   // Setup 페이지 레이아웃
};
export const SCREENS: Record<string, Screen> = Object.fromEntries(Object.entries(LOADERS).map(([k, f]) => [k, lazy(async () => ({ default: await f() }))]));
