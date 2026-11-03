// 휴지통 서버 접점(목록·복원·영구 삭제). [삭제](이동)는 옛 화면 상세에 남아 app.html trashApi.del 이 부른다(R5 까지).
// 응답 모양은 server/db.py trash_list — 견본 trash.sample.json 을 서버 시험(test_trash_flow.py)이 실제 응답과 대조한다.
import { getJSON, postJSON } from "../../shared/api";

export type TrashItem = {
  kind: string;
  id: string;
  title: string | null;
  trashed_at: string;
  purge_at: string;
  revision: number | null;
  restore_state: string | null;
  object_label?: string;
  reflection_kind?: string;
  occurred_on?: string | null;
};
export type TrashList = { items: TrashItem[]; next_cursor: string; hours: number };
export type TrashAct = "restore" | "purge";

export const trashList = (cursor: string) =>
  getJSON<TrashList>("/api/trash" + (cursor ? "?cursor=" + encodeURIComponent(cursor) : ""));

export const trashAct = (act: TrashAct, kind: string, id: string) =>
  postJSON<unknown>(`/api/trash/${act}`, { kind, id });
