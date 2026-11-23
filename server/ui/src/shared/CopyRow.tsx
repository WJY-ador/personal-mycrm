// 복사 줄 하나(2026-11-23 첫 기록 카드에서 옮김, 설정 AI 앱 연결 쪽이 쓴다) — 이름, 값 글자, [복사], 결과 한 줄.
// 결과 자리(role=status)는 처음부터 두고 글자만 채운다. 복사를 못 하면(권한 없음, 지원 안 함) 화면의 글자를 직접 골라 복사하게 안내한다
import { useState } from "react";
import css from "./CopyRow.module.css";

export const COPY_OK = "복사했어요";
export const COPY_FAIL = "복사하지 못했어요. 직접 골라 복사해 주세요.";

export function CopyRow({ id, label, value }: { id: string; label: string; value: string }) {
  const [say, setSay] = useState("");
  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(value);
      setSay(COPY_OK);
    } catch { setSay(COPY_FAIL); }
  };
  return (
    <div className={css.copyRow}>
      <span className={css.copyLabel}>{label}</span>
      <code className={css.copyValue} id={id}>{value}</code>
      <button type="button" onClick={() => void copy()} aria-label={`${label} 복사`}>복사</button>
      <span className={css.copySay} role="status">{say}</span>
    </div>
  );
}
