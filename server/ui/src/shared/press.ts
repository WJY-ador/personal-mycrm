// 버튼처럼 누르는 글자·카드(옛 data-rec·data-go + Enter·Space) — 키보드로도. 안쪽 요소에서 올라온 키는 무시(카드 안 링크가 따로 받는다).
import type { KeyboardEvent } from "react";

export const press = (go: () => void) => ({
  tabIndex: 0, role: "button", onClick: go,
  onKeyDown: (e: KeyboardEvent) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); go(); } },
});
