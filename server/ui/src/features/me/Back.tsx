// 1열(좁은 폭)에서만 — 상세 위 [돌아가기]·[목록]. 목록에서 왔으면 뒤로(목록 위치 그대로), 아니면 그 주소로
import { backNav, useMobile } from "./view";

export function Back({ to, label }: { to: string; label: string }) {
  if (!useMobile()) return null;
  const go = () => { if (backNav.fromList) { backNav.fromList = false; history.back(); } else location.hash = to; };
  return <p className="hback"><button className="secondary" type="button" onClick={go}>{label}</button></p>;
}
