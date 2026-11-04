// 턴 하나 — 사용자 글(오른쪽) · 도구 호출(접힘, 이름·결과 요약) · 답(rich 규칙 — **굵게** 만) · 끝 상태 한 줄. 답을 기다리는 동안 안내 1줄.
import { rich } from "../../shared/rich";
import type { Turn } from "./store";
import { WAITING } from "./text";
import css from "./Webchat.module.css";

export function TurnView({ t }: { t: Turn }) {
  return (
    <div className={css.turn} data-turn={t.id}>
      <p className={css.user}>{t.user}</p>
      {t.tools.length > 0 && (
        <details className={css.tools}><summary>{`도구 ${t.tools.length}번 사용`}</summary>
          <ul>{t.tools.map((x, i) => <li key={i}><code>{x.name}</code>{x.ok === undefined ? " …" : x.ok ? " ✓" : " ✕"}{x.summary ? ` — ${x.summary}` : ""}</li>)}</ul>
        </details>)}
      {t.answer ? <p className={css.answer}>{rich(t.answer, t.id)}</p> : !t.end && <p className={css.wait}>{WAITING}</p>}
      {t.end === "error" && <p className={css.note}>{t.endNote}</p>}
    </div>
  );
}
