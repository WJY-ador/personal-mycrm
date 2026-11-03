// 대시보드 React 화면 묶음. index.html 없이 src/main.tsx 하나를 진입으로 빌드하고, 서버(web.py)가 dist/.vite/manifest.json 을
// 시작 때 1회 읽어 /app/assets/<해시 이름> 허용 목록과 /app 의 <script type="module">·<link> 를 만든다.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: {
    manifest: true,
    rollupOptions: { input: "src/main.tsx" },
  },
  // 시험(vitest)이 ?raw 로 읽는 정적 뼈대 server/app.html(App.test) — 파일 하나만 허용하면 ?raw 꼴이 막혀 server/ 폴더를 허용(.env 는 기본 deny). 빌드와 무관
  server: { fs: { allow: [".", ".."] } },
  test: {
    environment: "jsdom",
    env: { TZ: "Asia/Seoul" },   // 날짜 표시 시험(사용자 시간대) — 옛 Python 시험과 같은 시간대
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
