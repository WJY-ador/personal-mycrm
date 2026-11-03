// 표시 이름 쓰기 — 기존 POST /api/me/name(세션 + Origin). 길이 규칙은 서버 문구 그대로(화면은 빈 값만 막는다)
import { postJSON } from "../../shared/api";

export const saveName = (display_name: string) => postJSON("/api/me/name", { display_name });
