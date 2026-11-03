// 못 읽음 표시 — 서버의 조치 문장(명령어 포함)은 그리지 않고 코드로 사람 말을 고른다(옛 app.html partFail·techInfo 그대로, 다른 옛 화면과 일시 중복)
import type { ApiError } from "../../shared/api";
import { FIXHINT } from "./text";

export function Tech({ err }: { err: ApiError }) {
  return <details className="tech"><summary>기술 정보</summary><code>{err.code}</code> {String(err.msg || "")}</details>;
}

export function PartFail({ err, what, recMissing }: { err: ApiError; what: string; recMissing: string }) {
  const say: Record<string, string> = { "RECORD-MISSING": recMissing, UNAUTHORIZED: "로그인이 풀렸어요.", OFFLINE: "서버에 연결하지 못했어요." };
  return (
    <div className="partfail" role="alert"><b>{what}을 읽지 못했어요 · 나머지는 정상</b>
      <p>{say[err.code] || "읽는 중에 문제가 생겼어요."} {FIXHINT}</p><Tech err={err} /></div>
  );
}
