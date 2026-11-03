// 문의 데스크(desk-0) 문구·고정 값 — 옛 app.html 문의 절·LABELS.ticketKind·ticketStatus 글자 그대로.
// DESK_MAX = 서버 db.LIMIT_TICKET(UTF-8 바이트) · DESK_NOTICE = 서버 db.NOTICE — 같은지는 server/test_web_home.py 가 본다
export const DESK_MAX = 4096;
export const DESK_NOTICE = "이 글은 서버에 저장되고 운영자가 직접 읽어요. 기록 원문이나 다른 사람 정보는 넣지 마세요.";
export const TICKET_KIND: Record<string, string> = { bug: "버그", request: "요청", question: "질문", privacy: "개인정보 요청" };
export const TICKET_STATUS: Record<string, string> = { open: "접수", ack: "확인", doing: "처리중", done: "완료", wontfix: "보류" };
export const DESK_CHIP: Record<string, string> = { open: "st-wait", ack: "", doing: "flag", done: "st-mine", wontfix: "st-off" };
export const DESK_LEAD = "안 되는 것·바라는 것·궁금한 것을 운영자에게 보내요. 처리 상태는 「내 문의」에서 보여요.";
export const DESK = {
  sending: "보내고 있어요…",
  sent: "보냈어요. 처리 상태는 「내 문의」에서 볼 수 있어요.",
  sendFail: "보내지 못했어요. 잠시 뒤 다시 보내 주세요.",
  listFail: "내 문의를 불러오지 못했어요. 새로 고침해 주세요.",
  empty: "아직 보낸 문의가 없어요.",
  oneFail: "문의를 불러오지 못했어요. 새로 고침해 주세요.",
  noReply: "아직 답변이 없어요.",
  noHist: "아직 처리 이력이 없어요.",
  noDesk: "이 계정에선 문의 창을 쓰지 않아요.",
};
