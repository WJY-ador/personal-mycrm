// 화면 폭 분기점 정본(디자인1 결정 4) — CSS media query 는 var(--…)를 못 쓰므로 값은 여기 한 곳에 적고, CSS 에는 같은 숫자를 쓴다.
// arch.test.ts 가 server/ui/src 의 모든 CSS @media 폭과 TS matchMedia 폭이 아래 값뿐인지 본다(다른 값이 들어오면 실패).
//   narrow  767  max-width 767 = 좁은 화면(1열·휴대폰), min-width 768 = 그 반대. shared/mobile.ts MOBILE 과 같은 값(옛 CSS 700 을 여기로 합침)
//   board   900  max-width — 2열 보드(.board·.struct)와 구조 서랍이 1열로
//   wide1000 1000 min-width = 판단 검토 2열(Review) · max-width = 활동 현황 4열 → 2열(Activity). 두 화면의 문턱이 같은 값
//   lens    1099 max-width — 「나」 렌즈 3열 → 2열(1100 미만)
//   wide    1240 min-width — 머리글 계정 이메일 칸을 넓힌다(.wrap 최대 폭과 같은 값)
export const BP = { narrow: 767, board: 900, wide1000: 1000, lens: 1099, wide: 1240 } as const;

// CSS·TS 에 쓸 수 있는 (방향, 폭) — 좁은 화면은 max 767 / min 768 짝
export const BP_ALLOWED = {
  max: [BP.narrow, BP.board, BP.wide1000, BP.lens],
  min: [BP.narrow + 1, BP.wide1000, BP.wide],
} as const;

export const maxW = (px: number) => `(max-width: ${px}px)`;
