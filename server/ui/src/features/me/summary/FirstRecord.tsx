// 첫 기록 카드(2026-11-23) — 기록이 하나도 없을 때 요약 맨 위. 조건은 Summary 가 본다(첫 글이 생기면 사라진다). 닫기 없음, 브라우저 저장소 안 씀.
// MCP 주소와 첫 마디(guides/09 2절)를 글자로 보이고 [복사]. 복사 결과는 그 자리 한 줄(role=status, 처음부터 두고 글자만 채운다).
// 복사를 못 하면(권한 없음, 지원 안 함) 화면의 글자를 직접 골라 복사하게 안내한다
import { useState } from "react";
import css from "./Summary.module.css";

export const FIRST_SAY = "오늘 있었던 일 기록 남길게.";
export const COPY_OK = "복사했어요";
export const COPY_FAIL = "복사하지 못했어요. 직접 골라 복사해 주세요.";

function CopyRow({ id, label, value }: { id: string; label: string; value: string }) {
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

export function FirstRecord() {
  return (
    <section className={css.firstRecord} id="first-record-intro" aria-labelledby="first-record-title">
      <h2 id="first-record-title">첫 기록을 남겨 보세요</h2>
      <p>Claude나 ChatGPT에 이 주소를 커넥터로 더하고 첫 마디를 보내요. 자세한 것은 <a href="/help">도움말</a>에서 볼 수 있어요.</p>
      <CopyRow id="first-record-mcp" label="MCP 주소" value={location.origin + "/mcp"} />
      <CopyRow id="first-record-say" label="첫 마디" value={FIRST_SAY} />
    </section>
  );
}
