// 기다림 캐릭터(2026-11-10 대화 하나로, 결정 9) — 숲 녹색 잎 하나가 살짝 흔들린다. 인라인 SVG와 CSS 움직임만(이미지 파일 0).
// label 이 있으면 role=status + 글자 하나(visible 이면 보이는 글자, 아니면 낭독기 전용 .sr). label 이 없으면 장식(aria-hidden) — 옆 글자가 따로 읽힌다.
// 움직임 줄이기 설정이면 멈춘다(CSS). 새 대화의 답 대기, PC 허용 대기, 옛 서랍 상태 줄이 같은 부품을 쓴다.
import css from "./Sprout.module.css";

export function Sprout({ label, visible = false }: { label?: string; visible?: boolean }) {
  const leaf = (
    <svg className={css.leaf} viewBox="0 0 24 24" aria-hidden="true" focusable="false" data-sprout="">
      <path className={css.body} d="M12 21.6c-5.3-1.7-8.1-5.7-7.5-10.7C5.1 6.1 8.3 3 12 2.4c3.7.6 6.9 3.7 7.5 8.5.6 5-2.2 9-7.5 10.7z" />
      <path className={css.rib} d="M12 21.4V12.8" />
      <circle className={css.eye} cx="9.5" cy="11.4" r="1.1" />
      <circle className={css.eye} cx="14.5" cy="11.4" r="1.1" />
    </svg>
  );
  if (!label) return <span className={css.wrap} aria-hidden="true">{leaf}</span>;
  return <span className={css.wrap} role="status">{leaf}<span className={visible ? css.text : "sr"}>{label}</span></span>;
}
