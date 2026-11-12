// 못 읽음 표시(옛 app.html partFail·techInfo) — 서버의 조치 문장(명령어 포함)은 그리지 않고 코드로 사람 말을 고른다. 판단 검토·질문·기록·구조·지도·원문이 쓴다.
import type { ApiError } from "./api";
import { FIXHINT, Tech } from "./Tech";

export const REC_MISSING = "글이 지워졌거나 찾을 수 없어요.";
// 오류 코드 → 사람 말(못 읽음 표시·껍데기 띠 공용)
export const FAIL_SAY: Record<string, string> = { "RECORD-MISSING": REC_MISSING, UNAUTHORIZED: "로그인이 풀렸어요.", OFFLINE: "서버에 연결하지 못했어요." };

export function PartFail({ err, what, recMissing = REC_MISSING }: { err: Pick<ApiError, "code" | "msg">; what: string; recMissing?: string }) {
  const say: Record<string, string> = { ...FAIL_SAY, "RECORD-MISSING": recMissing };
  return (
    <div className="partfail" role="alert"><b>{what}을 읽지 못했어요. 나머지는 정상이에요.</b>
      <p>{say[err.code] || "읽는 중에 문제가 생겼어요."} {FIXHINT}</p><Tech err={err} /></div>
  );
}
