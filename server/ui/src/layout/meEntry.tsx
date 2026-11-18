// 「나」·Setup 「페이지 레이아웃」 묶음(화면별 지연 불러오기 한 덩이) — 요약 블록 레지스트리.
// 블록 id 정본 = server/layout_registry.json(Python layout_check 와 같은 파일 하나 — 사본 금지). 키가 같은지는 registry.test.ts 가 본다.
import type { ScreenProps } from "../shared/ctx";
import reg from "../../../layout_registry.json";
import { MeScreen } from "../features/me/MeScreen";
import { LayoutScreen } from "../features/me/layout/LayoutScreen";
import type { Blocks } from "../features/me/summary/block";
import { Heatmap } from "../features/me/summary/Heatmap";
import { Kinds } from "../features/me/summary/Kinds";
import { Waiting } from "../features/me/summary/Waiting";
import { Recent } from "../features/me/summary/Recent";
import { answerMd } from "../features/webchat/answerMd";   // 축 한 장 = 웹 대화 답과 같은 렌더러(features 끼리 import 금지라 여기서 넘긴다)

export const REGISTRY = reg;
const BLOCK_LABEL = Object.fromEntries(Object.entries(reg.components).map(([k, v]) => [k, v.label]));
export const BLOCKS: Blocks = { heatmap: Heatmap, kinds: Kinds, waiting: Waiting, recent: Recent };

export const Me = (p: ScreenProps) => <MeScreen {...p} blocks={BLOCKS} layoutDefault={reg.pages.me.default} md={answerMd} />;
export const Layout = (p: ScreenProps) => <LayoutScreen {...p} def={reg.pages.me.default} blockLabel={BLOCK_LABEL} />;
