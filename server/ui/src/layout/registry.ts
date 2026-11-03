// 옮긴 화면 목록 + 「나」 요약 블록 레지스트리 — features 를 import 하는 유일한 곳. 화면 이름은 server/ui/migrated.json 의 screens 키와 같다.
// 블록 id 정본 = server/layout_registry.json(Python layout_check 와 같은 파일 하나 — 사본 금지). 키가 같은지는 registry.test.ts 가 본다.
import { createElement, type ComponentType } from "react";
import type { ScreenProps } from "../shared/ctx";
import reg from "../../../layout_registry.json";
import { TrashScreen } from "../features/trash/TrashScreen";
import { MeScreen } from "../features/me/MeScreen";
import { ReviewScreen } from "../features/review/ReviewScreen";
import { ChatRoot } from "../features/chat/ChatRoot";
import { MigrationScreen } from "../features/migration/MigrationScreen";
import { DevicesScreen } from "../features/devices/DevicesScreen";
import { ActivityScreen } from "../features/activity/ActivityScreen";
import { ObjectsScreen } from "../features/objects/ObjectsScreen";
import { TodayScreen } from "../features/today/TodayScreen";
import { LayoutScreen } from "../features/me/layout/LayoutScreen";
import { NameGate } from "../features/name/NameGate";
import { NameDialog } from "../features/name/NameDialog";
import { DeskDialog } from "../features/desk/DeskDialog";
import { HelpScreen } from "../features/desk/HelpScreen";
import { SheetScreen } from "../features/sheet/SheetScreen";
import { StructureScreen } from "../features/structure/StructureScreen";
import { DefsScreen } from "../features/defs/DefsScreen";
import { MapScreen } from "../features/map/MapScreen";
import { Mast } from "../features/mast/Mast";
import type { Blocks } from "../features/me/summary/block";
import { Heatmap } from "../features/me/summary/Heatmap";
import { Kinds } from "../features/me/summary/Kinds";
import { Waiting } from "../features/me/summary/Waiting";
import { Recent } from "../features/me/summary/Recent";

export const REGISTRY = reg;
const BLOCK_LABEL = Object.fromEntries(Object.entries(reg.components).map(([k, v]) => [k, v.label]));
export const BLOCKS: Blocks = { heatmap: Heatmap, kinds: Kinds, waiting: Waiting, recent: Recent };

export const SCREENS: Record<string, ComponentType<ScreenProps>> = {
  trash: TrashScreen,
  review: ReviewScreen,
  migration: MigrationScreen,
  devices: DevicesScreen,
  activity: ActivityScreen,   // 활동 목록·하나·축 하나(ctx.args = [activity|axis, …])
  objects: ObjectsScreen,     // 자료 종류 색인·사람·출처·읽고 든 생각(ctx.args = [a, b, c])
  today: TodayScreen,         // 오늘·저장 승인 대기(ctx.args = [today, a, b] | [inbox, 상태])
  sheet: SheetScreen,         // 질문·기록 탭(ctx.args = [탭 id, question|record, 조각, 고른 id])
  structure: StructureScreen, // 구조 항목·판단 문장 카드 + 항목 서랍(ctx.args = [a, b])
  defs: DefsScreen,           // 내 구조 설정(목록·그래프·이름 공유·표준 편입)
  map: MapScreen,             // 지도 칸반(ctx.args = [대조 경로 탭 id])
  chat: ChatRoot,   // 상시 섬(#ui-chat) — #view 화면이 아니다
  name: NameGate,         // 이름 관문(표시 이름 없을 때 #view)
  namedlg: NameDialog,    // 상시 섬(#ui-namedlg) — 「표시 이름 바꾸기」 대화창
  desk: DeskDialog,       // 상시 섬(#ui-desk, 관리자 응답엔 자리 없음) — 문의 보내기·내 문의
  help: HelpScreen,       // 설정 「문의 및 개인정보」
  mast: Mast,       // 상시 섬(#ui-mast — 머리글 스펙트럼·질문 레전드)
  me: (p: ScreenProps) => createElement(MeScreen, { ...p, blocks: BLOCKS, layoutDefault: reg.pages.me.default }),
  layout: (p: ScreenProps) => createElement(LayoutScreen, { ...p, def: reg.pages.me.default, blockLabel: BLOCK_LABEL }),   // Setup 페이지 레이아웃
};
