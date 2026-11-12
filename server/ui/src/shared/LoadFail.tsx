// 화면 조각 하나를 못 읽음(옛 loadFail) — 「<무엇>을 불러오지 못했어요 · 나머지는 정상」 + 사람 말 + 기술 정보(연결 실패는 빼고)
import type { ApiError } from "./api";
import { FIXHINT, Tech } from "./Tech";

// 받침 있으면 a, 없으면 b(을/를·이/가)
export function josa(w: string, a: string, b: string): string {
  const c = String(w).slice(-1).charCodeAt(0) - 0xAC00;
  return c < 0 || c > 11171 || c % 28 === 0 ? b : a;
}

// 「…으로/로」 — 받침 없거나 ㄹ 받침이면 로(편입 대화창 제목)
export function roJosa(w: string): string {
  const c = String(w).slice(-1).charCodeAt(0) - 0xAC00;
  return c < 0 || c > 11171 || c % 28 === 0 || c % 28 === 8 ? "로" : "으로";
}

export function LoadFail({ err, what }: { err: ApiError; what: string }) {
  const say = err.code === "NOT-FOUND" ? "찾을 수 없어요. 지워졌을 수 있어요." : err.code === "OFFLINE" ? "서버에 연결하지 못했어요." : "읽는 중에 문제가 생겼어요.";
  return (
    <div className="partfail" role="alert"><b>{what}{josa(what, "을", "를")} 불러오지 못했어요. 나머지는 정상이에요.</b><p>{say} {FIXHINT}</p>
      {err.code && err.code !== "OFFLINE" ? <Tech err={err} /> : null}</div>
  );
}
