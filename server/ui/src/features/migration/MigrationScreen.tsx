// Setup 「이관」(옛 renderMigration) — #_setup/migration[/<plan_id>]. ctx.args = [plan_id]. 목록 ↔ plan 하나는 key 로 갈라 앞 화면 상태
// (받은 토큰 원문·펼친 본문·오류)를 내린다. 결과 한 줄 = 그 주소 머리에 한 번(옛 coreDone), 쓰기 뒤엔 상태 한 벌을 다시 받는다(ctx.reload)
import { Crumbs } from "../../shared/Crumbs";
import type { ScreenProps } from "../../shared/ctx";
import { Flash, useFlash } from "../../shared/Flash";
import { MigList } from "./MigList";
import { MigPlan, type Done } from "./MigPlan";
import { MIG_LEAD } from "./text";

export function MigrationScreen({ ctx }: ScreenProps) {
  const { msg, say } = useFlash(ctx);
  const pid = ctx.args?.[0] || "";
  const done: Done = async (text, o = {}) => {
    say(text, !!o.bad, o.at);
    if (o.at) location.replace(o.at);
    await ctx.reload();
  };
  const dev: [string, string] = ["#_setup/devices", "연결 장치"];
  if (pid) return (
    <div className="paper sheet"><Crumbs xs={[dev, ["#_setup/migration", "이관"], ["", "plan"]]} /><Flash msg={msg} /><MigPlan key={pid} pid={pid} done={done} /></div>
  );
  return (
    <div className="paper sheet"><Crumbs xs={[dev, ["", "이관"]]} /><Flash msg={msg} /><h2 className="title">이관</h2>
      <p className="hint">{MIG_LEAD}</p><MigList key="list" done={done} /></div>
  );
}
