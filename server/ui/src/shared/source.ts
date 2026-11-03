// 출처 표기 — 기록의 source_id → S.sources 이름·종류(없으면 「출처 미확인」) · 옛 source 문자열(기록 당시 표기)은 보조. 옛 app.html srcText·srcLabel 과 같다.
import type { Source } from "./state";

export const SRC_NONE = "출처 미확인";
export const SRC_KIND: Record<string, string> = { file: "파일", url: "웹 주소", chat: "대화", other: "기타" };

export function srcText(sources: Source[] | undefined, sid: string | null): string {
  const x = sid ? (sources || []).find(s => s.id === sid) : undefined;
  return x ? `${x.name} · ${SRC_KIND[x.kind] || x.kind}` : SRC_NONE;
}

export const oldSrc = (raw: string | null | undefined) => (!raw ? "" : raw.startsWith("파일:") ? "파일에서 가져옴" : raw);

// 원문 머리말 한 줄 — 출처 + 옛 문자열(있으면)「쓸 당시 표기」(옛 srcLine)
export const srcLine = (sources: Source[] | undefined, sid: string | null, raw: string | null | undefined) =>
  srcText(sources, sid) + (oldSrc(raw) ? ` · 쓸 당시 표기 「${oldSrc(raw)}」` : "");
