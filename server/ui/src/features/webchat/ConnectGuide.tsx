// 연결 안내(대화 하나로 J-F1) — 쓸 수 있는 AI가 없으면 한 줄 문구 대신 3단계: 1 PC 앱 받기와 열기, 2 PC 연결, 3 Claude 또는 Codex 고르기.
// 멈춘 단계는 서버가 아는 상태(capabilities.setup)로만 정한다: none = PC 없음, offline = PC 는 있으나 PC 앱 꺼짐, no_provider = PC 앱은 켜졌으나 쓸 AI 없음.
// "PC 앱에서 열기" = mycrm:// 딥링크로 앱의 연결 장치 창을 그 칸으로 연다(앱이 없으면 아무 일도 없어서 받기 링크를 함께 둔다).
import type { Setup } from "./api";
import type { WebchatStore } from "./store";
import { GUIDE_DOWNLOAD, GUIDE_NOTE, GUIDE_OFFLINE, GUIDE_OPEN, GUIDE_RECHECK, GUIDE_STATE, GUIDE_STEPS, GUIDE_TITLE, appLink } from "./text";
import css from "./Webchat.module.css";

type StepState = "done" | "now" | "todo";
const STATES: Record<Exclude<Setup, "ready">, StepState[]> = {
  none: ["now", "todo", "todo"], offline: ["now", "done", "todo"], no_provider: ["done", "done", "now"],
};

export function ConnectGuide({ s }: { s: WebchatStore }) {
  const setup = s.capabilities.setup && s.capabilities.setup !== "ready" ? s.capabilities.setup : "none";
  const states = STATES[setup];
  const acts = (i: number) => {
    if (states[i] !== "now") return null;
    if (i === 2) return <a className="btn primary" href={appLink("provider")}>{GUIDE_OPEN}</a>;
    if (setup === "offline") return <a className="btn primary" href={appLink("connect")}>{GUIDE_OPEN}</a>;
    return <><a className="btn primary" href="/download" target="_blank" rel="noopener">{GUIDE_DOWNLOAD}</a>
      <a className="btn" href={appLink("connect")}>{GUIDE_OPEN}</a></>;
  };
  return (
    <section className={css.guide} aria-label={GUIDE_TITLE} data-setup={setup}>
      <h4>{GUIDE_TITLE}</h4>
      <p>{GUIDE_NOTE}</p>
      <ol>
        {GUIDE_STEPS.map((step, i) => (
          <li key={step.title} className={css.step} data-state={states[i]} aria-current={states[i] === "now" ? "step" : undefined}>
            <h5>{step.title} <span className={css.stepState}>{GUIDE_STATE[states[i]]}</span></h5>
            <p>{i === 0 && setup === "offline" ? GUIDE_OFFLINE : step.text}</p>
            {states[i] === "now" && <div className={css.stepActs}>{acts(i)}
              <button type="button" className="tertiary" disabled={s.capsLoading} onClick={() => void s.loadCapabilities()}>{GUIDE_RECHECK}</button></div>}
          </li>
        ))}
      </ol>
    </section>
  );
}
