// 이어 받지 않은 기록·문맥 API 밖 활동 노드의 이름 — 기존 읽기 API(본인 것만), 최대 30개. 받은 이름은 조회 캐시에 남는다(다시 그려도 다시 받지 않음)
import { useQueries } from "@tanstack/react-query";
import type { GNode } from "./links";
import { actName } from "./links";
import { meApi } from "./meApi";
import type { World } from "./model";
import { QK } from "./useWorld";

export function useNames(W: World, nodes: GNode[]): (n: GNode) => string {
  const lazy = [...new Map(nodes.filter(n => n.lazy).map(n => [n.key, n])).values()].slice(0, 30);
  const qs = useQueries({
    queries: lazy.map(n => n.kind === "journal"
      ? { queryKey: QK.journal(n.id), queryFn: () => meApi.journal(n.id), select: (j: { title: string }) => j.title }
      : { queryKey: ["activity", n.id], queryFn: () => meApi.activity(n.id), select: (a: Parameters<typeof actName>[1]) => actName(W, a) }),
  });
  const got = new Map(lazy.map((n, i) => [n.key, qs[i].data as string | undefined]));
  return n => got.get(n.key) || n.label;
}
