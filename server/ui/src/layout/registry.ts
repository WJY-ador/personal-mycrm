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
import type { Blocks } from "../features/me/summary/block";
import { Heatmap } from "../features/me/summary/Heatmap";
import { Kinds } from "../features/me/summary/Kinds";
import { Waiting } from "../features/me/summary/Waiting";
import { Recent } from "../features/me/summary/Recent";

export const REGISTRY = reg;
export const BLOCKS: Blocks = { heatmap: Heatmap, kinds: Kinds, waiting: Waiting, recent: Recent };

export const SCREENS: Record<string, ComponentType<ScreenProps>> = {
  trash: TrashScreen,
  review: ReviewScreen,
  migration: MigrationScreen,
  devices: DevicesScreen,
  activity: ActivityScreen,   // 활동 목록·하나·축 하나(ctx.args = [activity|axis, …])
  objects: ObjectsScreen,     // 자료 종류 색인·사람·출처·읽고 든 생각(ctx.args = [a, b, c])
  today: TodayScreen,         // 오늘·저장 승인 대기(ctx.args = [today, a, b] | [inbox, 상태])
  chat: ChatRoot,   // 상시 섬(#ui-chat) — #view 화면이 아니다
  me: (p: ScreenProps) => createElement(MeScreen, { ...p, blocks: BLOCKS, layoutDefault: reg.pages.me.default }),
};
