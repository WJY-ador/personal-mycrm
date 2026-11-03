// 「활동」 화면(옛 renderActivities·renderActivity·renderAxis) — 자료 종류 아래 #_obj/activity[/list/<쿼리>|/<활동 id>] · #_obj/axis/<항목 id>.
// ctx.args = [activity|axis, b, c]. 현황 접힘의 열림·기간은 이 화면이 떠 있는 동안 기억한다(목록 ↔ 상세를 오가도). 읽기 + [삭제](휴지통)만
import { useState } from "react";
import { Crumbs } from "../../shared/Crumbs";
import type { ScreenProps } from "../../shared/ctx";
import { Flash, useFlash } from "../../shared/Flash";
import { ActDetail } from "./ActDetail";
import { ActList } from "./ActList";
import type { Fold } from "./AggFold";
import { AxisView } from "./AxisView";

export function ActivityScreen({ ctx }: ScreenProps) {
  const [fold, setFold] = useState<Fold>({ open: false, period: "30d" });
  const { msg, say } = useFlash(ctx);
  const S = ctx.state!;
  const [a, b = "", c = ""] = ctx.args || [];
  const home: [string, string] = ["#_obj", "자료 종류"];
  if (a === "axis") return (
    <div className="paper sheet"><Crumbs xs={[home, ["", "축"]]} /><Flash msg={msg} /><AxisView key={b} S={S} id={b} /></div>
  );
  if (b && b !== "list") return (
    <div className="paper sheet"><Crumbs xs={[home, ["#_obj/activity", "활동"], ["", "활동 하나"]]} /><Flash msg={msg} /><ActDetail key={b} ctx={ctx} id={b} say={say} /></div>
  );
  return (
    <div className="paper sheet"><Crumbs xs={[home, ["", "활동"]]} /><Flash msg={msg} />
      <ActList S={S} qs={b === "list" ? c : ""} fold={fold} setFold={setFold} /></div>
  );
}
