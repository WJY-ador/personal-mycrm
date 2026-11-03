// 「눌러서 고치기」 상시 표시 — 작은 연필(인라인 SVG, 새 의존성 0). 터치 화면엔 hover 가 없어 고칠 수 있는 값을 늘 보이게 한다.
// 접근성 이름 「고치기」 — 값 버튼의 이름 = 값 글자 + 「고치기」. 옛 화면 클릭 편집(읽고 든 생각·표시 이름)도 옮길 때 이 표시를 쓴다(R4·R5).
import css from "./EditMark.module.css";

export function EditMark({ corner = false }: { corner?: boolean }) {
  return (
    <svg className={`${css.mark}${corner ? " " + css.corner : ""}`} viewBox="0 0 16 16" width="14" height="14" role="img" aria-label="고치기">
      <path d="M11.3 1.7a1.5 1.5 0 0 1 2.1 0l.9.9a1.5 1.5 0 0 1 0 2.1L5.6 13.4 2 14l.6-3.6z M10 3l3 3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
