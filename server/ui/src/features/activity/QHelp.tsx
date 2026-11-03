// 긴 계산 방법 = 숫자 제목 옆 「?」 도움말(누르면 펼침). 상시 문장으로 늘어놓지 않는다
import css from "./Activity.module.css";

export function QHelp({ t }: { t: string }) {
  return <details className={css.qhelp}><summary aria-label="계산 방법">?</summary><p>{t}</p></details>;
}
