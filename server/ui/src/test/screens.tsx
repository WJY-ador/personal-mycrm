// 시험 도우미 — 레지스트리 화면(지연 불러오기)을 시험에서 바로 띄운다: 모듈을 먼저 받아 두고 Suspense 로 감싼다(그리는 규칙은 껍데기와 같다).
// 상시 섬(머리글 스펙트럼·표시 이름·문의 대화창)은 껍데기(layout/App)가 바로 띄우는 것 — 같은 이름으로 같이 둔다.
import { Suspense, type ComponentType } from "react";
import { LOADERS, SCREENS as LAZY } from "../layout/registry";
import type { ScreenProps } from "../shared/ctx";
import { Mast } from "../features/mast/Mast";
import { NameDialog } from "../features/name/NameDialog";
import { DeskDialog } from "../features/desk/DeskDialog";

await Promise.all(Object.values(LOADERS).map(f => f()));
export const SCREENS: Record<string, ComponentType<ScreenProps>> = {
  ...Object.fromEntries(Object.entries(LAZY).map(([k, C]) => [k, (p: ScreenProps) => <Suspense fallback={null}><C {...p} /></Suspense>])),
  mast: Mast, namedlg: NameDialog, desk: DeskDialog,
};
