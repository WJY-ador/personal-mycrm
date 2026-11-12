// 모델 고르기 — 입력 칸 옆 버튼 하나(지금 모델 표시). 누르면 PC 가 알려 준 (공급자, 모델) 목록. PC 가 둘 이상이면 같은 목록 안에서 PC 로 묶는다.
// 진행 중 대화에서 다른 모델을 고르면 "이 모델로 새 대화를 시작해요" 확인 뒤 새 대화. 목록이 비면 이유와 할 일 한 줄(연결 장치 상태로 구분되는 만큼만).
// J-F5: 고른 것 = 표시 기호와 굵기, 포인터가 올라간 것 = 옅은 바탕(둘을 다른 모양으로). 계열마다 가장 새 판만 위에, 나머지는 "다른 모델"로 접는다.
// 고른 모델이 접힌 쪽에 있으면 처음부터 펼친다.
import { Sprout } from "../../shared/Sprout";
import { splitModels } from "./models";
import { choiceKey, type Choice, type WebchatStore } from "./store";
import { MORE_MODELS, NO_MODEL, PICK, PICK_LOADING, PICK_SWITCH, PICK_SWITCH_GO, PICKED, modelLabel, pcLabel } from "./text";
import css from "./Webchat.module.css";

export function ModelPicker({ s, dev }: { s: WebchatStore; dev: string }) {
  const cur = s.shown();
  const list = s.choices();
  const devices = [...new Set(list.map(c => c.device))];
  const label = cur && cur.provider ? modelLabel(cur.provider, cur.model) : s.capsLoading ? PICK_LOADING : PICK;
  const item = (c: Choice) => {
    const on = !!cur && choiceKey(cur) === choiceKey(c);
    return <li key={choiceKey(c)}><button type="button" className={css.pickItem} aria-pressed={on} title={on ? PICKED : undefined} onClick={() => s.pick(c)}>
      {modelLabel(c.provider, c.model)}</button></li>;
  };
  const group = (items: Choice[]) => {
    const { top, rest } = splitModels(items);
    const open = !!cur && rest.some(c => choiceKey(c) === choiceKey(cur));
    return <>
      <ul>{top.map(item)}</ul>
      {rest.length > 0 && <details className={css.more} open={open || undefined}>
        <summary>{`${MORE_MODELS} ${rest.length}개`}</summary>
        <ul>{rest.map(item)}</ul>
      </details>}
    </>;
  };
  return (
    <div className={css.picker} onKeyDown={e => { if (e.key === "Escape" && s.pickerOpen) { e.stopPropagation(); s.togglePicker(false); } }}>
      <button type="button" className={`tertiary ${css.pickBtn}`} aria-haspopup="dialog" aria-expanded={s.pickerOpen} aria-controls="webchat-models"
        title={PICK} disabled={s.waiting() || s.sending} onClick={() => s.togglePicker()}>
        <span className={css.pickName}>{label}</span><span aria-hidden="true">▾</span></button>
      {s.pickerOpen && <div className={css.pop} id="webchat-models" role="dialog" aria-label={PICK}>
        {s.pendingPick ? <div className={css.confirm}>
          <p>{PICK_SWITCH}</p>
          <p className={css.pickTo}>{modelLabel(s.pendingPick.provider, s.pendingPick.model)}</p>
          <div className={css.row}><button type="button" className="tertiary" onClick={() => s.togglePicker(false)}>취소</button>
            <button type="button" className="primary" onClick={() => s.confirmPick()}>{PICK_SWITCH_GO}</button></div>
        </div>
          : !list.length ? (s.capsLoading ? <Sprout label={PICK_LOADING} visible /> : <p className={css.noModel} role="status">{NO_MODEL[dev] ?? NO_MODEL[""]}</p>)
          : devices.length > 1 ? devices.map((d, i) => <section key={d} aria-label={pcLabel(i)}><h5 title={d}>{pcLabel(i)}</h5>
            {group(list.filter(c => c.device === d))}</section>)
          : group(list)}
      </div>}
    </div>
  );
}
