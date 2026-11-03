// 띠(옛 #bands) — 화면 전체에 걸리는 것만: 상태를 못 받음(연결 실패) · 탭 설정을 못 읽음
import { FAIL_SAY } from "../shared/PartFail";
import { FIXHINT, Tech } from "../shared/Tech";
import type { AppState } from "../shared/state";

export function OfflineBand({ loadedAt }: { loadedAt: string }) {
  return <div className="band fail" role="alert"><b>서버에 연결하지 못했어요.</b> 잠시 뒤 새로 고침해 주세요.
    {loadedAt ? ` 아래 화면은 ${loadedAt}에 불러온 내용이에요.` : ""}</div>;
}

export function TabsBand({ S }: { S: AppState }) {
  const err = S.read?.tabs?.error || { code: "", msg: "" };
  return <div className="band fail" role="alert"><b>탭 설정을 읽지 못해 기본 화면을 보여 드려요.</b> 내 탭은 지워지지 않았어요.
    {` ${FAIL_SAY[err.code] || ""} ${FIXHINT}`}<Tech err={err} /></div>;
}
