// 옛 껍데기(app.html)가 옮긴 화면에 넘기는 것. reload = 상태 한 벌을 다시 받는다(끝나면 껍데기가 crm:state 를 알린다).
export type UiCtx = { reload: () => Promise<unknown> };
export type ScreenProps = { ctx: UiCtx };
