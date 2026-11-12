// 입력 칸 키(대화 하나로 J-F4, JD4) — Enter = 보내기, Shift+Enter = 줄바꿈(Alt+Enter 도 보내지 않는다).
// 한글 조합 중의 Enter(isComposing, 또는 조합을 알리는 keyCode 229)는 글자를 확정하는 키라 보내지 않는다.
import type { KeyboardEvent } from "react";

export type KeyLike = Pick<KeyboardEvent, "key" | "shiftKey" | "altKey" | "keyCode"> & { nativeEvent?: { isComposing?: boolean } };
export function sendKey(e: KeyLike) {
  if (e.key !== "Enter" || e.shiftKey || e.altKey) return false;
  return !(e.nativeEvent?.isComposing || e.keyCode === 229);
}
