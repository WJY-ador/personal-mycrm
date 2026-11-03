// 대시보드 진입 — app.html 정적 뼈대의 #view(화면 자리)에 껍데기(layout/App) 하나를 띄운다. 첫 그리기가 「불러오는 중」 줄을 덮는다.
// 화면은 라우터가 고르고(지연 불러오기), 뼈대의 다른 자리(탭 줄·Setup 줄·띠·머리글·바닥·문의 자리)엔 포털로 그린다. CSS = 토큰 → 전역 기본 → 화면별 Modules 순.
import "./shared/tokens.css";
import "./shared/global.css";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { App } from "./layout/App";
import { queryClient } from "./shared/queries";

export function boot(el: HTMLElement | null = document.getElementById("view")) {
  if (!el) return null;
  const root = createRoot(el);
  root.render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
  return root;
}
boot();
