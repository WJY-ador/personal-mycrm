// 옮긴 화면 목록 — features 를 import 하는 유일한 곳. 이름은 server/ui/migrated.json 의 screens 키와 같다.
import type { ComponentType } from "react";
import type { ScreenProps } from "../shared/ctx";
import { TrashScreen } from "../features/trash/TrashScreen";

export const SCREENS: Record<string, ComponentType<ScreenProps>> = {
  trash: TrashScreen,
};
