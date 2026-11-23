// 설정 AI 앱 연결(#_setup/connect, 접지 않는 쪽, 2026-11-23 4차) — MCP 주소와 [복사], 연결 방법 세 줄, 첫 마디와 [복사], 도움말 링크. 읽기만, 요청 0.
// 연결 방법 문구 정본 = guides/09 1절 표(주소는 location.origin + /mcp). 복사 줄은 shared/CopyRow 한 벌
import type { ScreenProps } from "../../shared/ctx";
import { CopyRow } from "../../shared/CopyRow";
import css from "./Connect.module.css";
import { FIRST_SAY, LEAD, MCP_LABEL, MORE, SAY_LABEL, TITLE, WAYS_TITLE, mcpUrl } from "./text";

export function ConnectScreen(_: ScreenProps) {
  const url = mcpUrl();
  return (
    <div className="paper sheet"><h2 className="title">{TITLE}</h2>
      <p className="hint">{LEAD}</p>
      <CopyRow id="connect-mcp" label={MCP_LABEL} value={url} />
      <h3 id="connect-ways-title">{WAYS_TITLE}</h3>
      <ul id="connect-ways" aria-labelledby="connect-ways-title">
        <li><strong>Claude (claude.ai)</strong>: 설정 › 커넥터 › 커스텀 커넥터 추가 → 주소 <code>{url}</code> → 로그인 창에서 Google 또는 이메일 코드</li>
        <li><strong>Claude Code</strong>: <code>{`claude mcp add --transport http my-crm ${url}`}</code> 뒤 <code>/mcp</code> 에서 로그인</li>
        <li><strong>ChatGPT</strong>: Developer Mode 의 커넥터 추가(같은 주소). 2026-10 기준 Business 이상에서 쓰기 도구를 허용해요. Plus/Pro 는 아직 확인하지 못했어요.</li>
      </ul>
      <CopyRow id="connect-say" label={SAY_LABEL} value={FIRST_SAY} />
      <p className={`hint ${css.more}`}>{MORE[0]}<a href="/help">{MORE[1]}</a>{MORE[2]}</p>
    </div>
  );
}
