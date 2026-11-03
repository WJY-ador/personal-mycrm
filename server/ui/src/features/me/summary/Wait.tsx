// 통계 자리 — 받는 중이면 「불러오는 중」, 못 받았으면 새로 고침 안내(규칙은 서버 한 곳 — 화면에서 다시 세지 않는다)
import { LOADING, STATS_FAIL } from "../text";
import css from "./Summary.module.css";

export const Wait = ({ fail }: { fail: boolean }) => <p className={`hint${fail ? " " + css.fail : ""}`}>{fail ? STATS_FAIL : LOADING}</p>;
