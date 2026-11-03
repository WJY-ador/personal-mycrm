// 미저장 보호 대화창(옛 #leave-dlg) — 고치던 글이 있는 화면을 떠나려 할 때. 「계속 편집」 = 그 자리 입력 칸으로 · 「변경 버리기」 = 가려던 주소로
import { useEffect, useRef } from "react";

type P = { open: boolean; stay: () => void; go: () => void };

export function LeaveDialog({ open, stay, go }: P) {
  const dlg = useRef<HTMLDialogElement>(null), stayBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const d = dlg.current;
    if (!d) return;
    if (open) { if (!d.open) d.showModal?.(); stayBtn.current?.focus(); } else if (d.open) d.close?.();
  });
  return (
    <dialog ref={dlg} id="leave-dlg" aria-labelledby="leave-dlg-title" aria-describedby="leave-dlg-lead" onClose={() => { if (open) stay(); }}>
      <div className="dh"><b id="leave-dlg-title">저장하지 않은 변경이 있어요</b></div><div className="db">
        <p id="leave-dlg-lead">이 화면을 떠나면 고친 내용이 사라져요.</p>
        <div className="acts"><button ref={stayBtn} className="primary" type="button" id="leave-stay" onClick={stay}>계속 편집</button>
          <button className="secondary" type="button" id="leave-go" onClick={go}>변경 버리기</button></div>
      </div></dialog>
  );
}
