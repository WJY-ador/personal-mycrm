// 이름 관문 — 표시 이름이 비면 다른 화면 대신 이 화면(건너뛰기 없음). 탭·대화 서랍·띠는 껍데기가 비운다.
// 처리방침·문의 보내기·로그아웃은 그대로 — [문의 보내기]·[로그아웃]은 껍데기의 data-open 위임이 연다(문의 = 관리자 아님만, 서버 strip 과 같은 조건)
import { useEffect, useRef, useState } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { NameForm } from "./NameForm";
import css from "./Name.module.css";

export function NameGate({ ctx }: ScreenProps) {
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(""), [err, setErr] = useState("");
  useEffect(() => { input.current?.focus(); }, []);
  const desk = !ctx.state?.user?.admin;
  return (
    <div className={`paper ${css.gate}`}><div className="eyebrow">처음 한 번</div><h2 className="title">표시 이름을 정해 주세요</h2>
      <NameForm ctx={ctx} id="name-gate" input={input} value={value} setValue={setValue} err={err} setErr={setErr}
        acts={busy => <div className="frow"><button className="primary" type="submit" disabled={busy}>저장하고 시작하기</button></div>} />
      <div className={css.after}><a href="/privacy">개인정보 처리방침</a>{desk && <button className="tertiary" type="button" data-open="send">문의 보내기</button>}
        <button className="tertiary" type="button" data-open="logout">로그아웃</button></div>
    </div>
  );
}
