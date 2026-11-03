// 토큰 원문 상자(옛 tokenBox·migTokenBox) — 발급 응답을 받은 그 화면에서만 그린다. 원문은 부르는 쪽 useState 에만 있고
// (react-query 캐시·저장소·주소·콘솔에 넣지 않는다) [붙여 넣었어요 · 지우기] 또는 화면을 떠나면 지운다.
import { useRef, useState } from "react";
import css from "./TokenBox.module.css";

// paste = 붙여 넣을 곳 안내 한 문장 · copied = 복사 성공 문장 · lost = 잃어버렸을 때(괄호 안)
type Props = { title: string; region: string; inputLabel: string; paste: string; copied: string; lost: string; onDone: () => void; token: string };

export function TokenBox({ title, region, inputLabel, paste, copied, lost, onDone, token }: Props) {
  const [say, setSay] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  function copy() {
    const pick = (m: string) => { ref.current?.select(); setSay(m); };
    if (navigator.clipboard) navigator.clipboard.writeText(token).then(() => setSay(copied), () => pick("복사하지 못했어요. 선택된 글자를 직접 복사하세요."));
    else pick("선택된 글자를 직접 복사하세요.");
  }
  return (
    <div className={css.box} role="region" aria-label={region}><b>{title} — 지금 한 번만 보여요</b>
      <p>{`${paste} 이 화면을 떠나면 다시 볼 수 없어요(${lost}). 대화·문서·메신저에 붙여 넣지 마세요.`}</p>
      <div className="frow"><input ref={ref} className={`finput ${css.tok}`} type="text" readOnly value={token} aria-label={inputLabel} autoComplete="off" spellCheck={false} />
        <button type="button" className="secondary" onClick={copy}>복사</button><button type="button" className="tertiary" onClick={onDone}>붙여 넣었어요 · 지우기</button></div>
      <p className="fok" role="status" aria-atomic="true">{say}</p></div>
  );
}
