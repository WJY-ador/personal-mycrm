// 표준 편입 서버 접점 — 미리보기(/api/std/preview, 본인 것만·읽기 전용) · 선택(/api/std/choose: 보류·거절·편입). 응답 정본 = server/db.py std_preview.
// 견본 대조 = std.sample.json ↔ server/test_web_home.py test_ui_samples(키 집합까지). 이름 공유 동의 = /api/optional-consent(옛 계정 메뉴와 같은 API).
import { getJSON, postJSON } from "../../shared/api";

export type PvObj = {
  std_key: string; std_name: string; state: string; structure: string;
  object: { id: string; key: string; label: string; revision: number; archived: boolean } | null;
  conflicts: { code: string; field?: string | null }[]; meaning_check: boolean;
  needs: { field: string; std_key: string; state: string; ready: boolean }[];
  lock: { changes: string[]; fields: string[] }; can_incorporate: boolean; blocked: string[];
};
export type Preview = { version: string; objects: PvObj[] };
export const PV_KEY = ["std", "preview"];
export const stdApi = {
  preview: () => getJSON<Preview>("/api/std/preview"),
  choose: (o: PvObj, state: string) => postJSON("/api/std/choose", state === "incorporated"
    ? { std_key: o.std_key, state, confirmed_meaning: true, expected_revision: o.object ? o.object.revision : null } : { std_key: o.std_key, state }),
  names: (on: boolean) => postJSON("/api/optional-consent", { kind: "struct_names", on }),
};
