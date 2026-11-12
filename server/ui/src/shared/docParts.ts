// 기록 본문 나누기(옛 app.html splitDoc·attachHtml 과 같은 규칙 — R5 까지 일시 중복). 빈 줄 = 문단 경계.
// 화면 제목과 같은 「# 제목」 문단은 뺀다. 「## 이게 어디에 붙나」 절(키트 양식)은 따로 — 「- 키: 값」 줄만 표로.
export function splitDoc(body: string | null | undefined, title: string | null | undefined) {
  const parts = String(body || "").split(/\n\s*\n/).map(s => s.replace(/^\n+|\s+$/g, "")).filter(Boolean);
  const paras: string[] = [], attach: string[] = [];
  let inAttach = false;
  for (const p of parts) {
    if (/^##\s*이게 어디에 붙나/.test(p)) { inAttach = true; continue; }
    if (inAttach) { attach.push(p); continue; }
    if (/^#\s/.test(p) && p.replace(/^#\s+/, "").trim() === String(title || "").trim()) continue;
    paras.push(p);
  }
  return { paras, attach: attach.join("\n") };
}

const KEYS: Record<string, string> = { 질문: "질문", 판단: "판단 메모", 다음: "다음", 출처: "출처" };

// 「- 질문: <id>」 는 질문 문장으로(못 찾으면 안내) — qText(id) = 질문 문장 또는 null
export function attachRows(raw: string, qText: (id: string) => string | null): [string, string][] {
  const rows: [string, string][] = [];
  for (const line of raw.split("\n")) {
    const m = /^\s*-\s*([^:：]+)\s*[:：]\s*(.*)$/.exec(line);
    if (!m || !m[2].trim()) continue;
    const k = m[1].trim();
    let v = m[2].trim();
    if (k === "질문") { const q = qText(v); v = q ? q : "연결된 질문을 찾을 수 없음"; }
    rows.push([KEYS[k] || k, v]);
  }
  return rows;
}
