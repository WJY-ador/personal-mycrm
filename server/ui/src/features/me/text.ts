// 「나」 화면 문구·고정 값(옛 app.html 「나」 상세·v9 절 글자 그대로). 옛 쪽에 같은 이름이 남은 것(REFL_KIND·TRASH_ASK·SRC_KIND·LOADING 등)은
// 다른 옛 화면이 쓰는 일시 중복 — R5 에서 한쪽만 남는다(server/ui/migrated.json temp_duplicates).
import type { ApiError } from "../../shared/api";

export const ME_TABS = ["summary", "principle", "decision", "axis", "custom", "person", "source"] as const;
export type MeTab = (typeof ME_TABS)[number];
export const isTab = (t: string | undefined): t is MeTab => (ME_TABS as readonly string[]).includes(t || "");
export const ME_TAB_LABEL: Record<MeTab, string> = { summary: "요약", principle: "기준", decision: "결정", axis: "축", custom: "커스텀", person: "사람", source: "출처" };
export const ME_STD: Record<string, string> = { principle: "std:principles", decision: "std:decision_events", axis: "std:axes" };
export const ME_LOCKED = new Set(["principle", "decision", "axis", "person", "source"]);
export const ME_LENS: Partial<Record<MeTab, string>> = { principle: "근거 역추적", decision: "근거 역추적", axis: "축 묶음", person: "사람 관계" };
export const URL_KINDS = ["journal", "q", "cand", "item", "refl"];

export const ME_EMPTY = "아직 표시할 데이터가 없어요. 데이터가 들어오면 여기서 볼 수 있어요.";
export const STATS_FAIL = "통계를 불러오지 못했어요. 새로 고침해 주세요.";
export const GONE = "이 데이터를 열 수 없어요.";
export const LOADING = "불러오는 중이에요…";
export const NO_CONN = "연결된 데이터가 없어요.";
export const CONN_FAIL = "연결을 불러오지 못했어요.";
export const MORE_FAIL = "더 불러오지 못했어요. 다시 눌러 주세요.";
export { SRC_KIND, SRC_NONE } from "../../shared/source";
export const REFL_KIND: Record<string, string> = { summary: "내 요약", reaction: "내 반응" };
export const TRASH_ASK = "삭제하면 휴지통으로 이동해요. 삭제 시각부터 168시간 동안 복원할 수 있고, 이후 서버 정리 때 영구 삭제돼요.";
export const TRASH_DONE = "휴지통으로 옮겼어요.";
export const OFFLINE = "서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.";

export const firstLine = (s: string | null | undefined) => (String(s || "").split("\n").find(l => l.trim()) || "").trim();

// 기존 쓰기(표시 이름·읽고 든 생각·판단·항목 결정) 실패 — 원인 + 다음 행동 2문장(옛 homeErrText 그대로)
export function oldErrText(e: ApiError): string {
  if (e.code === "CONFLICT") return "다른 곳에서 먼저 바뀌었어요. 최신 내용을 다시 불러왔으니 확인하고 다시 해 주세요.";
  if (e.code === "OFFLINE") return OFFLINE;
  if (e.code === "CANDIDATE-REVIEW") return `${e.msg || "근거 글이 인용 조건에 맞지 않아 남길 수 없어요."} 반영 안 함으로는 표시할 수 있어요.`;
  const m = String(e.msg || "저장하지 못했어요.").trim();
  return `${/[.?!요]$/.test(m) ? m : m + "."} 고친 뒤 다시 해 주세요.`;
}

// 수기 수정(기록 본문·제목·항목) 실패 — 서버 문구(msg)와 다음 행동(action)을 그대로. 화면이 문구를 짓지 않는다(연결 실패만 화면 문구)
export const serverErrText = (e: ApiError) => (e.code === "OFFLINE" ? OFFLINE : [e.msg, e.action].filter(Boolean).join(" ") || "저장하지 못했어요.");
