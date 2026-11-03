// 기술 정보(옛 techInfo) — 오류 코드·서버 문구를 접어서. 사람 말은 부르는 쪽이 고른다(서버 조치 문장·명령어는 그리지 않는다).
import type { ApiError } from "./api";

export const FIXHINT = "새로 고침해도 그대로면 다시 로그인해 보세요.";

export function Tech({ err }: { err: Pick<ApiError, "code" | "msg"> }) {
  return <details className="tech"><summary>기술 정보</summary><code>{err.code}</code> {String(err.msg || "")}</details>;
}
