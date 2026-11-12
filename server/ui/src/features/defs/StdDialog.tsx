// 편입 확인 대화창(옛 #std-dlg·stdConfirm) — 「이 자료 종류를 표준 ○○ 와 같은 뜻으로 쓴다」 + 잠금 영향. 체크해야 [편입하기]가 켜진다(confirmed_meaning=true).
import { useEffect, useRef, useState } from "react";
import type { PvObj } from "./stdApi";
import { josa, LOCK_TEXT, roJosa } from "./text";

export function StdDialog({ o, go, close }: { o: PvObj | null; go: (o: PvObj) => void; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null), ok = useRef<HTMLInputElement>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => { const d = ref.current; if (o && d && !d.open) { setChecked(false); d.showModal?.(); ok.current?.focus(); } if (!o && d?.open) d.close?.(); }, [o]);
  const nm = o?.std_name || "", obj = o?.object, lock = o?.lock || { changes: [], fields: [] };
  return (
    <dialog id="std-dlg" ref={ref} aria-labelledby="std-dlg-title" aria-describedby="std-dlg-lead" onClose={close}>
      <div className="dh"><b id="std-dlg-title">{o ? `표준 ${nm}${roJosa(nm)} 편입하기` : "표준으로 편입하기"}</b>
        <button className="small" type="button" onClick={close}>닫기</button></div><div className="db">
        <p id="std-dlg-lead">{!o ? "" : obj ? `내 자료 종류 ${obj.label}에 표준 식별자를 달아요. 데이터와 항목은 그대로예요.`
          : `같은 키의 자료 종류가 없어 표준 ${nm} 정의를 새로 넣어요.`}</p>
        <h3>편입하면 막히는 변경</h3><ul>{lock.changes.map(ch => <li key={ch}>{LOCK_TEXT[ch] || ch}</li>)}</ul>
        <p className="hint">{lock.fields.length ? `잠기는 표준 필드: ${lock.fields.join(", ")}` : ""}</p>
        <p className="hint">이름은 계속 바꿀 수 있고, 필드와 선택지는 더할 수 있어요. 편입한 뒤엔 보류나 거절로 되돌릴 수 없어요.</p>
        <label className="stdok"><input type="checkbox" ref={ok} checked={checked} onChange={e => setChecked(e.target.checked)} />{" "}
          <span>{!o ? "" : obj ? `이 자료 종류를 표준 ${nm}${josa(nm, "과", "와")} 같은 뜻으로 써요. 아래 잠금 영향을 확인했어요.` : `표준 ${nm} 정의를 새로 넣어요. 아래 잠금 영향을 확인했어요.`}</span></label>
        <div className="acts"><button className="primary" type="button" disabled={!checked} onClick={() => { if (checked && o) go(o); }}>편입하기</button>
          <button className="tertiary" type="button" onClick={close}>취소</button></div>
      </div></dialog>
  );
}
