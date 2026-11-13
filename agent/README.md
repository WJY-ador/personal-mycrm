# agent — 로컬 에이전트 (호스팅 판 「연결 장치」)

내 PC 를 호스팅 판 계정에 「연결 장치」로 붙이는 프로그램입니다. 수집기 산출물을 활동과 수집 글로 바꿔 서버에 보내고, 다른 사람의 원문 본문은 PC 에 둡니다. 서버엔 행동·날짜·별칭·HMAC 식별자·관계 같은 구조화 정보, 수집 글의 URL, 제목 줄, 작성자 표시, 날짜, AI 요약과 분석, 그리고 내가 승인할 글만 갑니다.

- Python ≥3.9, 표준 라이브러리만. 키트 루트(이 `agent/` 폴더의 상위)에서 `python3 -m agent …` 로 돌립니다.
- macOS: 자격 증명은 Keychain(`security` CLI), 예약은 launchd. Windows: 자격 증명은 Credential Manager, 예약은 Task Scheduler. Windows 는 실제 PC 에서 아직 검증하지 않았습니다(아래 「Windows」).
- 무엇을 보내고 무엇을 PC 에 두는지는 [처리방침](../guides/11-privacy.md) 2절 「연결 장치와 PC 원문」. 화면 용어는 [말 뜻](../guides/10-words.md) 「연결 장치와 활동」.

## 1. 명령

```bash
python3 -m agent [--home 경로] <명령>
```

| 명령 | 하는 일 |
|---|---|
| `connect --server https://<주소>` | 토큰만 받습니다(비표시 입력). 입력원 ID·장치 이름·허용 규칙·정책 판·키 공간·만료는 서버 `GET /api/imports/device` 에서 받아 확인합니다. 확인되면 토큰을 Keychain 에 넣고, 그 키 공간의 HMAC 키가 없으면 새로 만들어 둡니다. 서버 확인이 실패하면 아무것도 저장하지 않습니다. `--label`·`--hmac-namespace`·`--policy-revision`·`--axis` 는 서버 값을 덮어쓸 때만 씁니다 |
| `connect … --token-stdin` | 토큰을 표준 입력 한 줄로 받습니다(화면 표시 없음) |
| `connect … --browser` | 앱 없이 브라우저 로그인으로 토큰을 받습니다(2절). 출력에 로그인한 계정이 나옵니다 |
| `validate [파일 …]` | 설정과 전송 대기 파일(`pending/`)·지정 파일을 계약(`canon-inbox/1`)으로 검사합니다. 쓰지 않습니다 |
| `run-once` | 수집 → 변환 → 계약 검증 → 전송 대기 저장 → (켰으면) 요약 → 업로드를 한 번 합니다. 같은 홈에서 겹쳐 돌면 뒤엣것은 건너뜁니다. 토큰 만료가 30일 안이면 업로드 뒤 토큰을 자동으로 바꿉니다(2절). 교체가 실패해도 종료 코드는 바뀌지 않습니다. `--no-rotate` 면 교체를 건너뜁니다(데스크톱 앱은 앱 세션으로 교체해 이 플래그를 넘깁니다) |
| `run-once --no-upload` | 전송 대기 저장까지만 |
| `run-once --resume <범위>` | 멈춘 범위(`auth`·`config`·`account`·`policy`·`forbidden`·`summary`)를 내가 조치한 뒤 풉니다 |
| `run-once --scheduled` | 예약이 부르는 꼴(0~5분 지연, 무인 실행으로 신고). 손으로 쓰지 않습니다 |
| `status` | 연결·토큰·키 유무, 켜진 어댑터, 무인 요약, 예약, 건수(이벤트·대기·접수·멈춤·충돌·거절·삭제됨·격리·사람), 오늘 요약 시도, 멈춤 범위 |
| `configure-cli --path <절대경로>` | 무인 요약이 부를 구독 CLI 실행 파일 경로를 `config.json` 에 저장합니다. 절대 경로·있는 파일·실행 가능해야 하고(Windows 는 `.exe`), 아니면 아무것도 바꾸지 않고 종료 코드 1로 끝납니다. 무인 요약을 켜지 않습니다 |
| `configure-cli --clear` | 저장된 CLI 경로만 지웁니다. 다른 설정은 그대로입니다 |
| `ai-status` | AI 연결 상태를 JSON 한 줄 `{"ai": {"claude": {"state": 상태, "code": 이유}, "codex": {…}}}` 로 냅니다. 상태 = `linked`(CLI 로그인 됨, 끊기 표시 없음), `signed_out`(CLI 있음, 로그인 안 됨 — API 키 같은 구독 아닌 인증은 code `unsupported-auth`), `off`(이 PC 에서 끊음), `missing`(CLI 없음, 또는 대화가 실행을 거절할 파일 — code `untrusted-cli`). 공급자 CLI 의 `claude auth status --json`·`codex login status` 를 대화(`chat`)와 같은 환경으로 부르고, 계정 정보는 내지 않습니다. Codex 대화가 준비되기 전(`CHAT_CODEX_PROVIDER_READY` 꺼짐)에는 `codex` 를 자동으로 실행하지 않습니다(`ai-status`, 대화 시작, 턴마다 확인). 그동안 Codex 는 `signed_out`(code `unchecked`) 또는 `missing` 이고, 사용자가 앱에서 Codex 연결을 누를 때(`ai-connect --provider codex`)만 실행합니다. Codex 실행 파일도 Claude 와 같은 소유자, 쓰기 권한 검사를 거칩니다. 저장된 경로가 없으면 PATH 와 표준 설치 위치(`~/.local/bin` 등)에서 찾아 `summary.cli_path`·`summary.codex_cli_path` 에 저장합니다 |
| `ai-connect --provider claude\|codex` | 끊기 표시를 지우고, 로그인이 없으면 공급자 로그인(`claude auth login --claudeai`, `codex login`)을 띄웁니다. 3초마다 상태를 보며 최대 5분 기다립니다. 로그인 프로세스가 10초 안에 실패로 끝나면(TTY 가 필요한 경우) 같은 명령을 시스템 터미널로 띄웁니다(macOS `open -a Terminal`, Windows `cmd /c start`). 인증은 공급자 CLI 가 보관합니다 |
| `ai-disconnect --provider claude\|codex` | 이 PC 에서 MyCRM 이 그 공급자를 쓰지 않게 표시합니다(`ai-connection.json`). 공급자 로그아웃은 하지 않습니다 |
| `schedule install` · `schedule remove` | 현재 사용자 예약 등록(1시간마다)·해제. macOS 는 launchd, Windows 는 Task Scheduler. 둘 다 여러 번 해도 같습니다. 해제는 원문·대응표를 지우지 않습니다 |
| `serve [--port N]` | 원문 보기(127.0.0.1 전용, 기본 포트 8790). Ctrl+C 로 끕니다 |
| `serve --jobs` | 작업 실행 상주(11절, 준비 중 · 기본 꺼짐). 끝내기 = Ctrl+C·SIGTERM, 실행 중 작업은 최대 30초 기다립니다 |
| `chat --fake` | 웹 「대화」 연결 상주(준비 중 · 서버 스위치 기본 꺼짐). 서버에 WebSocket 하나로 붙어 받은 턴을 실행해 출력을 올립니다. 지금은 가짜 대본(`--fake`)만 — 실 CLI 는 다음 단계. 끊기면 1초부터 최대 60초까지 늘려 다시 붙고, 서버가 확인하지 않은 출력만 다시 보냅니다(턴을 다시 실행하지 않음). 서버 신호가 50초 동안 없으면(잠자기·네트워크 전환 — 메시지를 반쯤 받다 멈춘 경우 포함) 연결을 닫고 다시 붙습니다. 메시지 하나는 64KB 를 넘지 않게 나눕니다(긴 답은 쪼개고, 큰 도구 데이터는 줄여 표시). 토큰이 거절되면 Keychain 을 한 번 다시 읽어 바뀌었으면(자동 교체·재발급) 새 토큰으로 이어 가고, 같으면 종료 코드 3 으로 멈춥니다. 시작 때 `ai-status` 와 같은 AI 연결 상태를 보고, `linked` 인 공급자의 모델만 알리며 상태를 hello 의 `ai_links` 로 서버에 보고합니다(PC 앱 허용 창은 없습니다). 대화가 시작될 때마다 다시 보고 `linked` 가 아니면 그 턴을 `AI-OFF`·`AI-SIGNED-OUT`·`AI-MISSING` 으로 거절합니다. 앱이 연결을 바꾸면(제어 줄 `{"command":"ai-refresh"}`) 다시 보고 같은 연결에서 hello 를 다시 보냅니다 |
| `disconnect` | 순서대로 ① 서버 토큰 폐기(`POST /api/imports/device/revoke`) ② 로컬 업로드 토큰 제거. 서버가 장애·네트워크 오류면 로컬 토큰을 그대로 두고 종료 코드 1로 멈춥니다(다시 시도). 토큰이 이미 폐기·만료됐으면 서버는 「이미 무효」로 보고 로컬만 지웁니다. 결과는 서버·로컬·HMAC 키를 따로 보여 줍니다. HMAC 키는 지우지 않습니다 |
| `disconnect --local-only` | 서버를 건너뛰고 로컬 토큰만 지웁니다 — 웹 「연결 장치」에서 이미 해제했을 때 |
| `disconnect --forget-hmac-key` | 그 키 공간의 HMAC 키도 지웁니다. **지우면 같은 사람 연결이 끊깁니다** — 다시 연결해도 전에 본 사람을 같은 사람으로 잇지 못하고, 서버의 HMAC 으로 되살릴 수 없습니다. 백업 없이 쓰지 마세요 |

종료 코드: 0 성공 · 1 오류 · 2 쓰는 법 · 3 멈춤(사용자 조치 필요 — 출력 마지막 줄의 안내 뒤 `--resume`).
출력에는 토큰·HMAC 키·원문·실명·URL 을 쓰지 않습니다.

오류 자동 보고: `run-once` 가 멈추거나(종료 코드 3, `auth` 제외) 실행에 실패하면(종료 코드 1) 장치 토큰으로 운영자에게 보고합니다(`POST /api/device/error-reports`). 담는 것은 출처(`agent`), 단계(`run-once/halt`·`run-once/failed`), 고정 오류 코드(`halt-policy`, `run-error` 등, 꼴이 어긋나면 `unknown`), 앱 버전, OS 종류(`mac`·`win`·`other`), 시각, 횟수뿐입니다. 본문, 경로, URL, 토큰, 오류 문장은 담지 않습니다. 네트워크 실패나 5xx 면 한 번만 다시 보내고, 그 밖의 실패는 무시합니다.

미확인(2026-11-13): `claude auth login` 이 TTY 없이 끝까지 되는지(그래서 터미널 대체 경로를 둡니다), `codex login status` 의 종료 코드(0 = `linked`, 1 = `signed_out` 으로 둡니다).

## 2. 처음 연결하기 (macOS)

연결 경로는 네 가지입니다. 어느 경로든 토큰은 화면·대화·명령줄에 나오지 않고 Keychain 에만 들어갑니다.

| 상황 | 하는 일 |
|---|---|
| 데스크톱 앱이 있다 | 앱에 로그인하면 앱이 이 PC 를 자동으로 연결합니다(시작 때, 로그인 뒤, 동기화 전에도 다시 확인). 할 일이 없습니다 |
| 대화에서 먼저 연결하고 싶다 | 대화에서 「PC 연결해 줘」라고 말합니다. 켜져 있는 앱이 토큰을 받아 `connect --token-stdin` 으로 넣습니다. 앱이 꺼져 있으면 켜기만 하면 됩니다 |
| 앱 없이 키트만 쓴다(이 PC 에 브라우저가 있다) | `python3 -m agent connect --server https://<주소> --browser` — 브라우저에서 로그인하면 끝납니다(아래 설명) |
| 원격 셸(이 PC 에 브라우저가 없다) | 아래 1~2단계 — 웹에서 토큰을 발급해 `connect --token-stdin` 으로 표준 입력에 넘깁니다 |

`--browser` 는 RFC 8252 loopback 입니다. 에이전트가 `127.0.0.1` 임의 포트에서 한 번만 기다리고, PKCE(S256)·state 를 만들어 시스템 브라우저로 서버 로그인(`/desktop/login`)을 엽니다. 로그인하면 서버가 `http://127.0.0.1:<포트>/cb` 로 일회용 코드(2분)를 돌려주고, 에이전트가 그 코드와 verifier 로 `POST /desktop/cli/claim` 을 불러 토큰을 받아 Keychain 에 넣습니다. 장치 이름은 `--label`, 없으면 이 PC 의 호스트 이름입니다. 5분 안에 로그인하지 않으면 멈춥니다. 브라우저가 안 열리면 출력된 주소를 **이 PC 의** 브라우저로 여세요. 실행할 때마다 서버에 새 장치가 생기고 옛 장치는 남습니다 — 안 쓰는 장치는 웹·대화에서 해제하세요. 토큰을 받으면 서버 확인 전에 Keychain 에 먼저 넣습니다. 확인이 네트워크로 실패하면 그대로 두고 다음 `run-once` 가 확인을 마칩니다(`status` 에 「서버 확인 대기」). 서버가 그 토큰을 거절하면 지웁니다. 이관 토큰도 같은 방식으로 받습니다: `migrate login --server https://<주소> --browser`.

토큰 만료가 30일 안으로 들어오면 `run-once` 가 업로드 뒤 스스로 새 토큰으로 바꿉니다(`POST /api/device/rotate`). 새 토큰은 Keychain 대기 자리(`upload-token-pending:<입력원 ID>`)에 먼저 두고, 새 토큰으로 서버 확인이 되면 본 자리로 옮깁니다. 옛 토큰은 서버에서 새 토큰이 처음 쓰일 때 무효가 됩니다. 그래서 응답이 끊겨도 옛 토큰으로 계속 보내고, 다음 실행이 다시 확인합니다. 90일 동안 업로드가 없던 장치는 서버가 교체를 거절합니다 — 만료 전에 위 경로로 다시 연결하세요. 서버가 교체를 거절하면 24시간 동안 다시 묻지 않습니다(안내는 하루 한 번, 네트워크 실패는 다음 실행에 바로 다시). `connect` 로 새 토큰을 넣으면 이 기다림은 풀립니다. 다른 계정 토큰으로 `connect` 하면 이 PC 에서 옛 계정 토큰을 지웁니다.

1. 웹에서 새 탐색을 수락한 계정으로 로그인 → 계정 메뉴 「연결 장치」 → 장치 이름을 적고 연결. 토큰은 **그 화면에서 한 번만** 보입니다. 대화·문서·메신저에 붙여 넣지 마세요.
2. 키트 루트에서:
   ```bash
   python3 -m agent connect --server https://<주소>     # 「업로드 토큰(화면에 안 보임):」 에 붙여 넣기
   ```
   출력에 입력원 ID·정책 판·허용 행동·토큰 만료·설정 파일 위치가 나옵니다.
3. 설정 파일(`<홈>/config.json`)의 `adapters.likes` 를 채웁니다 — 아래 3절.
4. 보내기 전에 확인:
   ```bash
   python3 -m agent run-once --no-upload
   python3 -m agent validate
   python3 -m agent status
   ```
5. 보내기 → 예약 → 원문 보기:
   ```bash
   python3 -m agent run-once
   python3 -m agent schedule install
   python3 -m agent serve
   ```
   서버 스위치가 꺼져 있으면(화면 「준비 중」) 업로드는 대기 파일로 남고 다음 실행에 다시 보냅니다.

## 3. 설정 (`config.json`)

설정엔 토큰·HMAC 키를 넣지 않습니다(Keychain 항목 이름만). 입력 경로는 전부 이 파일에서 옵니다. `connect` 가 서버 주소·입력원 ID·허용 규칙을 채웁니다. 내가 채우는 것은 어댑터와 요약입니다.

`likes` 예시(`config.example.json` 과 같음):
```json
{
  "config_version": 1,
  "adapters": {
    "likes": {
      "enabled": true,
      "input_path": "/absolute/path/to/likes.jsonl",
      "provider_code": "threads",
      "include_kinds": ["*"],
      "include_null_kind": true,
      "include_seed": true,
      "axes": []
    }
  }
}
```
- `input_path` — 수집기 `likes.jsonl` 의 절대 경로. `provider_code` — HMAC 제공자 코드(소문자, 예: 플랫폼 이름).
- `include_kinds`·`include_null_kind`·`include_seed` — 보낼 행. 코드 기본값은 **아무 행도 안 보냄**(`[]`·`false`·`false`)이라, 보내려면 이렇게 직접 적어야 합니다. `["*"]` = kind 가 있는 행 전부. kind 는 내가 붙인 분류 태그라 좋아요 여부와 무관하고, 축 매핑에도 쓰지 않습니다.
- `axes` — 모든 활동에 붙일 축 항목 ID. 웹 「연결 장치」 허용 규칙의 축 안에서만 됩니다.
- 변환 규칙: 행 하나 = `like` 활동 하나. 행동 날짜를 주는 필드가 없어 `occurred_on` 은 언제나 비움(「날짜 미확인」) — 게시 시각·수집 시각으로 대신하지 않습니다. `first_seen` 은 「처음 수집한 날」(`observed_on`)로만 갑니다. 작성자 핸들은 HMAC 으로만 가고, 본문·게시 시각·원 URL·주제 등 나머지는 PC 원문 저장소에만 둡니다. 파일에서 행이 사라져도 취소를 만들지 않습니다. 판별할 수 없는 중복은 격리하고 보내지 않습니다.
- 수집 글 어댑터(`feed`, `reactions`, `mail`)는 기본으로 꺼져 있습니다. 켜는 법은 아래 3-1절입니다.
- `kakao` 는 의미 규칙만 있는 골격이라 켤 수 없습니다. 카톡 글은 `feed` 어댑터의 채널 `kakao` 로 들어옵니다(feed-queue `source: "kakao"`). 내가 보내고 답한 행동을 담은 입력 파일이 생기면 그때 켭니다.
- LinkedIn 이직 입력원(`linkedin_moves`)은 설정에 적으면 설정 오류로 막습니다.
- 그 밖: `viewer_port`(원문 보기 포트, 기본 8790 — 웹 활동 상세의 「로컬 연결 포트」와 같게), `upload`(`max_per_run` 100 · `min_interval_sec` 6.5 · `timeout_sec` 30).

## 3-1. 수집 글 어댑터 (`feed`, `reactions`, `mail`, 기본 꺼짐)

수집기(로그인된 브라우저로 긁는 프로그램)가 만든 JSONL 을 읽습니다. 수집 자체는 이 에이전트가 하지 않습니다. 줄 하나가 JSON 객체 하나이고, UTF-8 입니다.

**서버로 가는 것과 PC 에 두는 것**
- 수집 글(`collected-post/1`)은 다른 사람의 글입니다. 서버엔 원 URL(`post_url`), 제목 줄(본문 첫 줄 앞 200자, 요약 아님), 작성자 표시 이름, 게시일, 수집일, 축, 수집기 AI 가 만든 요약과 분석(`ai`)만 갑니다. 원문 본문 전체, 작성자 소개는 PC 원문 저장소(`raw_id`)에 두고 [5절](#5-원문-보기-serve)로 엽니다.
- 수집 글은 승인 대기 없이 바로 항목이 됩니다. 내 판단의 근거가 아니고, AI 문장은 `ai` 안에만 둡니다.
- 작성자는 표시 이름 글자로만 갑니다. 사람 항목, HMAC 식별자를 만들지 않습니다.
- 제목 줄, 작성자 표시, AI 문장 안의 URL, 이메일, 로컬 경로 덩어리는 `‹링크›`, `‹메일›`, `‹경로›` 로 가리고 보냅니다. 가린 수는 `run-once` 결과의 `masked` 에 남습니다. 가린 뒤 제목 줄에 가림 표시만 남으면 그 글은 격리합니다. URL 은 `post_url` 에만 갑니다(`https://` 로 시작, 2,000자 이하).
- 활동(내 행동)은 명시된 것만 만듭니다. 행동 날짜(`occurred_on`)는 명시적 행동 시각(`reacted_at`, 보낸 메일의 `ts`)에서만 채우고 수집 시각으로 대신하지 않습니다. 활동엔 작성자 정보를 붙이지 않습니다.
- 날짜는 KST 날짜로 자릅니다. 오프셋(`Z`, `+09:00`, `+0900`)이 없는 시각은 쓰지 않습니다.
- 같은 원천 ID 는 한 항목입니다. 다시 실행하면 바뀐 필드만 새 개정으로 갱신합니다(예: AI 요약이 나중에 채워짐). 같은 ID 의 행이 여럿이면 파일의 마지막 행을 씁니다(URL 이 바뀌어도 같은 항목을 갱신).
- 판별할 수 없는 행(ID, 수집일, 제목 줄 없음, 모르는 상태, 채널)은 격리하고 보내지 않습니다.

**설정 예시** (`connect` 뒤 `<홈>/config.json` 의 `adapters` 에 더합니다. 경로는 절대 경로)
```json
"feed": {
  "enabled": true,
  "input_path": "/absolute/path/to/feed-queue.jsonl",
  "axes_map": {"<원천 축 코드>": "i_<축 항목 ID>"}
},
"reactions": {
  "enabled": true,
  "inputs": [
    {"path": "/absolute/path/to/reactions.jsonl", "format": "reactions", "channel": "linkedin"},
    {"path": "/absolute/path/to/threads-likes.jsonl", "format": "threads_likes", "channel": "threads"}
  ]
},
"mail": {"enabled": true, "input_path": "/absolute/path/to/mail.jsonl"}
```
- `feed.channels` — 원천 `source` 값 → 채널(`linkedin`, `reddit`, `kakao`, `threads`, `blog`, `web`). 기본값: `source` 없음, `linkedin`, `linkedin_search` → `linkedin`, `reddit`, `kakao`, `brunch`, `naver_blog` → `blog`, `web`. 값을 `null` 로 적으면 그 `source` 는 보내지 않습니다. 매핑에 없는 `source` 는 격리합니다.
- `feed.axes_map` — 원천 축 코드 → 축 항목 ID. 웹 연결 장치 허용 규칙의 축 안이어야 합니다. 매핑에 없는 코드는 버립니다(최대 10개).
- `reactions.inputs` — 파일마다 `format`(`reactions` 또는 `threads_likes`)과 `channel` 을 적습니다. `channel` 은 `kakao` 를 쓸 수 없습니다(반응 활동의 제공자에 카톡이 없습니다). `reactions.kind_actions` — 원천 `kind` → 활동(기본 `like`, `comment`, `repost`, `reply` 그대로). 매핑에 없는 `kind` 는 활동 없이 격리 기록만 남기고, 수집 글은 그대로 보냅니다.
- `threads_likes` 입력은 수집 글만 만듭니다. 좋아요 활동은 `likes` 어댑터가 만듭니다. 그래서 같은 Threads 좋아요 파일을 두 어댑터가 함께 읽어도 활동이 겹치지 않습니다.
- 웹 연결 장치 허용 규칙에서 변환(`collected-post/1`, `board-feed/1`, `board-reactions/1`, `board-mail/1`)과 행동(`save`, `comment`, `repost`, `reply`, `read`, `send`)을 켜야 서버가 받습니다. 꺼져 있으면 만들지 않고 건너뜁니다(`run-once` 결과의 `skipped_policy`). 웹에서 켜면 다음 실행이 허용 규칙을 다시 받아 만듭니다.
- 서버 계정에 커스텀 오브젝트 `collected_posts` 가 있어야 수집 글을 받습니다.

**웹 판별 되돌림 (`feed.write_back`, 기본 `false`)**

웹 오늘 탭에서 보관하거나 버린 수집 글을 이 PC 의 feed 입력 파일에도 반영합니다. 켜려면 `"feed": {..., "write_back": true}` 로 적습니다.
- `run-once` 가 업로드를 마친 뒤 서버에서 사용자 판별 목록을 받습니다(업로드 토큰, 커서는 PC 상태 저장 `state.sqlite` 에 둡니다). 꺼져 있으면 목록을 받지 않고 커서도 옮기지 않습니다. 나중에 켜면 그 전 판별부터 받습니다.
- 판별 항목을 이 PC 의 feed 에서 올린 원천 `id` 로 찾고, 그 `id` 의 마지막 행(어댑터가 읽는 행)의 `status` 가 `pending` 일 때만 `status`(`kept` 또는 `dropped`)와 `decided_at`(서버가 남긴 판별 시각)을 바꿉니다. 그 밖의 필드와 다른 줄은 그대로 둡니다. 대시보드에서 먼저 판별한 행(`pending` 이 아닌 행)은 건너뜁니다.
- 대시보드, 수집기와 같이 잠금 없이 원자 교체로 씁니다. 읽은 뒤 파일이 바뀌었으면 한 번 다시 읽어 재시도하고, 그래도 바뀌면 이번 실행엔 쓰지 않습니다. 파일 권한은 그대로 둡니다.
- 한 번에 200건씩 받고, 서버가 더 있다고 하면(`has_more`) 이어 받습니다. 요청 사이엔 업로드와 같은 간격(`upload.min_interval_sec`)을 둡니다(장치 분당 한도를 업로드와 같이 씁니다). 사용자가 판별을 되돌린 항목(`pending`)은 파일을 바꾸지 않습니다.
- 커서는 그 쪽을 파일에 다 쓴 뒤에만 옮깁니다. 서버 오류, 형식 오류, 파일 바뀜, 한도 초과(429)면 커서를 그대로 두고 다음 실행에 다시 받습니다. 서버가 커서를 모른다고 하면(400 `ARG-INVALID`) 커서를 버리고 처음부터 한 번 받습니다. 판별 목록 실패는 업로드 멈춤을 만들지 않습니다.
- 결과 JSON 의 `write_back: {applied, skipped_not_pending, missing, retried, stopped}` — 바꾼 행 수, `pending` 이 아니라 건너뛴 수, 이 PC feed 에서 찾지 못한 수(다른 장치나 `reactions` 에서 올린 항목, 파일에서 사라진 행), 재시도 수, 멈춘 이유(`null` 이면 끝까지 받음). 항목 ID, 원천 ID, 경로는 남기지 않습니다.
- 상태 다시 보내기(`state_resync`, 한 번): 이 판의 첫 `run-once` 때 대응표의 수집 글(`feed`, `reactions`) 중 서버에 항목이 있는 것을 대상으로 올리고, 수집 때 같은 필드의 새 개정(이전 개정 = 마지막 접수 개정, 지금 허용 규칙 판)을 만들어 보냅니다. 서버는 내용이 같으면 바꾸지 않고(noop) 받으면서 상태(`state`)만 채웁니다. `write_back` 설정과 무관하게 돕니다. 새 수집 글 몫을 남기려고 한 실행에 50건, 한 KST 날에 300건까지만 만듭니다(장치 수집 글 하루 한도 500). 입력에서 사라진 행은 같은 필드를 만들 수 없어 보내지 않고 닫습니다. 결과 JSON `state_resync: {queued, sent, done, unseen, failed}` — 이번 실행에 만든 새 개정 수, 이번 실행에 접수된 수, 남은 대상이 없는지, 보내지 못하고 닫은 누적 수(입력에서 사라진 행, 거절되었거나 지금 허용 규칙으로 만들 수 없는 행). `done` 은 다 보냈다는 뜻이 아니라 더 할 것이 없다는 뜻입니다. 하루 몫은 새 개정을 만들 때마다 남겨 실행이 중간에 끊겨도 넘지 않습니다. 끝난 표시는 `state.sqlite` 에 둡니다.
- 다음 `run-once` 때 바뀐 행은 그 `status` 로 다시 올라갑니다(`kept` → `state: kept` 와 `save` 활동, `dropped` → `state: removed`). 서버는 사용자가 판별한 항목의 상태를 장치 재전송으로 덮지 않습니다.

**입력 JSONL 필드 (수집기 출력 계약)** — 표에 없는 필드는 PC 원문 저장소에만 둡니다.

`feed` (feed-queue 꼴) → 수집 글 + 보관이면 `save` 활동

| 필드 | 꼴 | 쓰는 곳 |
|---|---|---|
| `id` | 문자열, 필수 | 중복 기준(PC 대응표에만) |
| `status` | `pending`, `kept`, `dropped`, `expired`, `excluded`, `superseded`, 필수 | `pending`, `kept` → 수집 글 `state`. 나머지는 새로 올리지 않고, 이미 올린 글이면 `state: removed`(서버 휴지통). `kept` → `save` 활동 |
| `text` | 문자열, 필수 | 첫 줄 앞 200자 → `title`. 전체는 PC 에만 |
| `collected_at` | 오프셋 있는 시각 또는 `YYYY-MM-DD`, 필수 | KST 날짜 → `collected_on`, `save` 활동의 `observed_on` |
| `source` | 문자열 또는 없음 | `feed.channels` 로 → `channel` |
| `post_url` | `https://` URL | → `post_url` |
| `author` | 문자열 | → `author_display` |
| `published_at` | 오프셋 있는 시각 또는 날짜 | KST 날짜 → `posted_on`. 없으면 비움 |
| `axes` | 축 코드 문자열 목록 | `feed.axes_map` 으로 → `axes`(수집 글과 `save` 활동) |
| `grade` | `signal`, `news`, `noise` | → `ai.grade` |
| `summary` | 문자열 | → `ai.summary`(500자에서 자름) |
| `long` | `{asis, tobe, ops, points[]}` | → `ai.as_is`, `ai.to_be`, `ai.ops`(각 1,000자), `ai.points`(12개, 각 300자) |
| `author_desc` 등 | | PC 에만 |

`reactions` (`format: "reactions"`) → 수집 글(`state: kept`) + 반응 활동

| 필드 | 꼴 | 쓰는 곳 |
|---|---|---|
| `id` | 문자열, 필수 | 중복 기준 |
| `text` | 문자열, 필수 | 첫 줄 → `title`. 전체는 PC 에만 |
| `collected_at` | 시각 또는 날짜, 필수 | → `collected_on`, 활동의 `observed_on` |
| `kind` | 문자열 | `reactions.kind_actions` 로 → 활동 `like`, `comment`, `repost`, `reply`. 같은 `id` 에 `kind` 가 여럿이면 행동마다 하나 |
| `reacted_at` | 오프셋 있는 시각 | KST 날짜 → 그 활동의 `occurred_on`. 없으면 비움 |
| `post_url`, `author`, `posted_at` | | → `post_url`, `author_display`, `posted_on` |

`reactions` (`format: "threads_likes"`, Threads 좋아요 꼴) → 수집 글(`state: kept`)만. 좋아요 활동은 `likes` 어댑터 몫

| 필드 | 꼴 | 쓰는 곳 |
|---|---|---|
| `id` | 문자열, 필수 | 중복 기준 |
| `text` | 문자열, 필수 | 첫 줄 → `title` |
| `first_seen` | `YYYY-MM-DD`, 필수 | → `collected_on` |
| `original_url`, `author`, `posted_at` | | → `post_url`, `author_display`, `posted_on` |

`mail` (mail 꼴) → 활동만. 수집 글을 만들지 않습니다

| 필드 | 꼴 | 쓰는 곳 |
|---|---|---|
| `url`, `acct`, `from_email`, `ts`, `subject` | | 다섯 값을 함께 다이제스트해 중복 기준으로만 씁니다(PC 대응표에만) |
| `unread` | 불리언 | `false` 일 때만 `read` |
| `saved`, `sent`, `replied` | 불리언, 있으면 | `true` 일 때 `save`, `send`, `reply`. 수신, 목록에 있다는 것만으로는 활동을 만들지 않습니다 |
| `ts` | 오프셋 있는 시각 또는 epoch(초, 밀리초) | `send` 의 `occurred_on` 만 |
| `first_seen` | `YYYY-MM-DD` | → `observed_on` |
| `subject`, `snippet`, `from_name`, `from_email`, `acct` | | PC 에만. 서버로 가지 않습니다 |

## 4. 무인 요약 (기본 꺼짐)

`summary.enabled` 는 `false` 가 기본입니다. 구독 CLI 의 이용 조건·권한 제한·CLI 자체 보관 동작을 확인하기 전에는 켜지 않습니다. 요약은 실행 방식대로 신고합니다 — 내가 직접 돌린 `run-once`(`--scheduled` 없이)는 사람이 돌린 것(`attended`)이라 서버의 가져오기 스위치만으로 접수되고, 예약 실행(`--scheduled`, launchd)은 무인(`unattended`)이라 서버 스위치 `CRM_UNATTENDED_SUMMARY_IMPORTS_ENABLED` 도 켜져 있어야 접수됩니다(그 스위치는 따로 꺼져 있습니다).

켜는 조건과 동작:
- `input_dir` — 사람이 지정하고 확인한 **내 기록 전용** 폴더의 절대 경로. 다른 사람의 말·고객사 정보가 섞인 폴더를 모델에게 골라내게 하지 않습니다. 숨김 파일·심볼릭 링크는 읽지 않고, `file_glob_suffix`(기본 `.md`) 파일만 봅니다.
- `cli_path` — 이미 로그인해 쓰는 구독 CLI 의 절대 경로. `tool_code`(기본 `claude-cli`)·`model_code`(기본 `unknown`)는 서버에 신고하는 값입니다.
- 모델에는 업로드 토큰·HMAC 키·신원 매핑을 넘기지 않습니다(최소 환경변수, 빈 작업 폴더, 입력은 표준 입력). 도구·MCP 를 끄고 1턴만 돌립니다.
- 성공 = 종료 코드 0 **그리고** 계약 검증 통과. 실패 출력은 전송 대기에 넣지 않습니다. 5분 제한(`timeout_sec` 300) · 동시 1개 · PC 당 KST 하루 10회 시도(`daily_attempts`).
- 로그인·구독·권한 오류면 `summary` 범위가 멈춥니다. 조치한 뒤 `run-once --resume summary`.
- 요약은 서버 「승인 대기」로 가고, 내가 웹에서 승인해야 기록이 됩니다. 승인해도 AI 생성 표시가 남습니다.
- 웹에서 삭제한 요약은 입력 파일이 바뀌어도 바로 다시 요약하지 않습니다(구독 사용 0). 휴지통이면 168시간 뒤 입력이 바뀌어 있을 때 한 번 다시 요약해 보내고(복원했으면 접수), 영구 삭제했으면 더는 요약하지 않습니다.
- 지금 에이전트는 내 글(`self-text/1`)을 만드는 어댑터가 없습니다. 승인 대기로 가는 것은 AI 요약과 세션 정리(아래)입니다. 수집 글(3-1절)은 승인 대기 없이 바로 항목이 됩니다.

## 4-1. 세션 정리 폴더 (기본 꺼짐)

AI 와 나눈 대화를 내가 정리해 둔 「세션 정리」 글(`YYYY-MM-DD.md`)을 묶음마다 내 글로 보냅니다. 모델은 쓰지 않습니다.

```json
"session_wrap": {"enabled": true, "folders": ["/absolute/path/to/session-wrap-folder"]}
```

- `folders` — 세션 정리 글이 있는 폴더의 절대 경로 목록(최대 20). 폴더 바로 아래의 `YYYY-MM-DD.md` 파일만 읽습니다(하위 폴더·숨김·심볼릭 링크·다른 이름은 건너뜀). 이 목록은 이 PC 설정에만 둡니다.
- 묶음 하나 = `## 제목` 줄부터 다음 `##`·`#`·`---` 줄 앞까지 → 내 글 하나(제목 = 그 줄, 원본 날짜 = 파일 이름 날짜). `### 소제목` 은 본문에 그대로 둡니다. 머리말·`# 세션 스토리` 머리줄은 보내지 않습니다.
- `→ 남긴 곳:` 줄은 빼고 보냅니다(어디에 남겼는지 가리키는 줄). `정본 후보:` 줄은 남깁니다(내 말 한 줄).
- 같은 묶음의 문단을 고치면 새 개정, 제목을 고치면 새 글로 갑니다.
- 제목·본문의 로컬 경로(`~/`·`/Users/` 등으로 시작하는 덩어리)는 `‹경로›` 로 가리고 보냅니다. URL·이메일이 있거나 길이 한도를 넘으면 보내지 않고 격리합니다.
- 웹 「연결 장치」 허용 규칙에서 「세션 정리(승인 대기)」가 켜져 있어야 만듭니다(새 장치는 기본으로 켜짐). 꺼져 있으면 아무것도 만들지 않습니다.
- 서버 「승인 대기」에서 내가 승인하면(웹, 또는 대화에서 말하면) 기록이 됩니다. 이 기록은 내가 결정한 정리 글로 다뤄져, 원문 그대로가 아니어도 판단 후보의 근거로 쓸 수 있습니다.

## 5. 원문 보기 (`serve`)

웹 활동 상세의 [이 PC에서 원문 열기] 는 `http://127.0.0.1:<포트>/raw/<원문 ID>` 로 갑니다. 수집 글의 원문 본문도 같은 원문 ID(`raw_id`)로 엽니다.
- `127.0.0.1` 에만 붙습니다. 첫 화면은 **원문 없는 확인 화면**이고, 그 화면의 [원문 열기] 를 눌러야 원문을 보여 줍니다(같은 출처 요청 · 정확한 Host·Origin · 세션 · 60초 일회용 토큰).
- 요청에서 경로·URL·파일명을 받지 않습니다. 원문 위치는 PC 대응표로만 찾고, 저장소 밖으로 벗어나는 경로는 거절합니다. 다른 사람의 HTML 은 실행하지 않고 글자로 보여 줍니다. 외부 이미지·글꼴·스크립트가 없고, 캐시·리퍼러·프레임 삽입을 막습니다. 접근 로그를 남기지 않습니다.
- 다른 PC 에서는 같은 ID 라도 대응표가 없어 열리지 않습니다. 이 방어는 웹 페이지의 무단 접근을 줄이는 것이고, 같은 OS 계정에서 도는 악성 프로그램까지 막는다고 보장하지 않습니다.
- 휴대폰·태블릿에서는 원문을 열 수 없습니다.

## 6. 멈췄을 때

| 보이는 것 | 할 일 |
|---|---|
| 「서버가 토큰을 거절했어요…」(`auth`) | 웹 「연결 장치」에서 토큰 재발급 → `connect` 다시 → `run-once --resume auth` |
| 「입력원 ID 가 토큰과 달라요…」(`config`) | `connect` 다시 → `run-once --resume config` |
| 「웹에서 표시 이름을 먼저 정한 뒤…」(`account`) | 웹에서 표시 이름 정하기 → `run-once --resume account` |
| 허용 규칙 변경 | 웹에서 허용 규칙을 바꾸면 다음 업로드가 「장치 허용 규칙이 바뀌었어요」(`POLICY-STALE`)를 받습니다. 에이전트가 같은 토큰으로 새 규칙을 다시 받아 설정을 고치고, 아직 접수되지 않은 대기 요청을 새 판으로 다시 만들어 그 실행에서 한 번 다시 보냅니다 — 토큰을 다시 넣지 않습니다. 출력의 `policy_refresh` 에 결과(`ok`·다시 만든 수·새 규칙이 막아 뺀 수)가 나옵니다 |
| 「…자동으로 다시 받지 못했어요…」(`policy`) | 장치 정보를 받지 못했거나(서버·네트워크), 입력원·키 공간이 바뀌었거나, 설정의 `likes.axes` 가 새 허용 축 밖입니다. 다음 실행이 다시 시도합니다. 계속되면 `connect` 를 다시 한 뒤 `run-once --resume policy` |
| 「서버가 요청을 막았어요…」(`forbidden`) | 웹 「연결 장치」를 확인한 뒤 `run-once --resume forbidden` |
| `status` 의 「멈춤 N」(`SOURCE-REVISION-CONFLICT`) | 서버의 최신 판과 PC 판이 갈라진 것입니다. Phase 1 에는 자동 해소가 없습니다 — 해당 원본은 보내지 않고 남겨 두고, 운영자에게 알려 수동으로 정리합니다. 다른 원본은 계속 갑니다. 정리 전에 홈을 백업해 둡니다 |
| 「충돌」·「거절」·「격리」 건수 | 같은 요청 키에 다른 본문, 계약·허용 규칙 불일치, 판별할 수 없는 중복입니다. 보내지 않고 남겨 둡니다(원문·식별자 없이 요약 값만) |
| `status` 의 「삭제됨 N」 | 웹에서 휴지통으로 보내거나 영구 삭제한 원본입니다. 같은 내용은 다시 보내지 않습니다. 내용이 바뀌면 보내지만, 서버가 그 원본을 휴지통·삭제 상태로 두는 동안은 받지 않습니다. PC 원문은 지우지 않습니다 |
| 업로드가 다음 날로 미뤄짐 | 일일 한도(활동 하루 500건·사람 새로 50명 등)에 닿았습니다. 서버가 알려 준 시각(대개 다음 KST 0시) 뒤 다시 보냅니다. 서버 스위치가 꺼져 있거나 네트워크 오류면 대기 파일을 두고 최대 1시간 간격으로 다시 시도합니다 |

## 7. 파일과 Keychain

- **홈** = `--home` > 환경변수 `MYCRM_AGENT_HOME`(에이전트 전용 이름 — 서버의 `CRM_*` 환경변수와 다른 접두입니다) > OS 기본. macOS `~/Library/Application Support/my-crm-agent` · Windows `%APPDATA%\my-crm-agent` · 그 밖 `~/.local/share/my-crm-agent`. 제품 폴더(레포) 밖입니다.
- 홈 안: `config.json`·`state.sqlite`(현재 사용자만 읽기·쓰기) · `raw/`(다른 사람 원문·원 URL — **PC 에만**) · `pending/`(검증된 서버 요청만) · `locks/` · `logs/`(예약 실행 출력) · `summary-work/` · `rotate-state.json`(토큰 교체를 서버가 마지막으로 거절한 시각·코드, 있을 때만 — 토큰 값 없음) · `connect-pending.json`(`connect --browser` 의 서버 확인 대기 — 서버 주소·입력원 ID 만, 있을 때만). 폴더는 현재 사용자만 열 수 있게 만듭니다.
- `state.sqlite` = 수집 이벤트 ↔ 불투명 원본 ID·개정·원문 ID·사람 HMAC 대응표와 전송 상태.
- Keychain: 서비스 `my-crm-agent`, 항목 `upload-token:<입력원 ID>`(업로드 토큰) · `upload-token-pending:<입력원 ID>`(자동 교체로 받아 서버 확인 전인 새 토큰, 있을 때만) · `hmac-key:<키 공간 ID>`(HMAC 키, 256비트). 평문 파일로 대신 저장하지 않습니다.
- **HMAC** = `HMAC-SHA256(PC 키, JCS(["person/1", 제공자 코드, 계정 식별자]))`. 표시 이름만으로 사람을 정하지 않고, 제공자가 다르면 같은 사람으로 합치지 않습니다. 키를 잃으면 서버의 HMAC 으로 원래 사람을 되살릴 수 없습니다. 여러 PC 에서 같은 사람을 유지하려면 같은 키와 대응표를 내가 안전하게 옮겨야 합니다.
- **예약**: `~/Library/LaunchAgents/local.mycrm.agent.plist`(현재 사용자 LaunchAgent 하나, 1시간마다). plist·명령줄·환경변수에 토큰이 없습니다. 실행 폴더는 등록할 때의 키트 위치와 Python 으로 고정되므로, 키트를 옮기거나 Python 을 바꾸면 `schedule install` 을 다시 합니다. 설치 패키지의 실행 파일(frozen)로 등록하면 실행 폴더는 키트 위치 대신 그 실행 파일의 폴더입니다. PC 가 잠들거나 꺼져 있으면 돌지 않습니다.

## 8. 백업과 지우기

- **백업 권고**: 홈 전체(`raw/`·`state.sqlite`·`config.json`)와 Keychain 의 HMAC 키를, 내가 관리하는 **암호화 백업 한 곳**에 함께 둡니다. 원문과 대응표는 자동으로 지우지 않습니다. HMAC 키 없이 대응표만 있으면 같은 사람 연결을 이어 갈 수 없습니다.
- 서버 계정을 삭제해도 PC 의 원문·대응표·Keychain 항목은 그대로입니다. 연결 해제(`disconnect`)·예약 해제(`schedule remove`)·PC 원문 삭제는 서로 다른 작업입니다. PC 쪽 자료를 지우려면 예약을 해제하고 연결을 끊은 뒤 홈 폴더를 지우고, Keychain 의 `my-crm-agent` 항목을 지웁니다.

## 9. Windows

**실제 Windows PC 에서는 아직 검증하지 않았습니다.** 아래 동작은 단위 시험(모의 Credential Manager API·모의 `schtasks`)으로만 확인했습니다.

- **자격 증명**: Credential Manager 의 현재 사용자 generic credential 에 둡니다. 대상 이름은 `my-crm-agent:<항목>`(항목은 7절 Keychain 과 같은 `upload-token:<입력원 ID>`·`hmac-key:<키 공간 ID>`)입니다. 저장한 뒤 다시 읽어 같은지 확인합니다. 저장소를 못 쓰면 멈추고, 평문 파일로 대신 저장하지 않습니다.
- **예약**: `schedule install` 이 Task Scheduler 에 현재 사용자 작업 하나를 등록합니다(1시간마다, 로그온한 동안·최소 권한, 겹치면 새 실행을 건너뜀). 작업 정의 XML 은 `%APPDATA%\my-crm-agent\schedule\agent-task.xml`(홈을 바꿨으면 `<홈>\schedule\agent-task.xml`)에 둡니다. XML·명령줄에 토큰·암호가 없습니다. `schedule remove` 는 작업만 지웁니다. 원문·대응표는 지우지 않습니다.
- 지우기: 예약을 해제하고 연결을 끊은 뒤 홈 폴더를 지우고, Credential Manager 의 `my-crm-agent:` 항목을 지웁니다.

## 10. 시험

```bash
python3 -m unittest discover -s agent/tests   # 키트 루트에서. Keychain·launchctl·구독 CLI 는 모의 실행기
```
서버 공용 시험 벡터(`server/contract/imports/vectors/`)와 이전 명세 스키마가 없으면 그 시험은 건너뜁니다.

## 11. 작업 전달 (`jobs.py`, 준비 중 · 기본 꺼짐)

웹에서 들어온 작업(대화 정리 등)을 서버가 이 PC 에 맡기고, PC 가 구독 CLI(`claude -p`)로 한 번 실행해 결과를 돌려주는 부분입니다. 상주 실행 명령은 `python3 -m agent serve --jobs` 입니다. 서버의 작업 스위치(`CRM_CONVERSE_ENABLED`·`CRM_ROUTINE_ENABLED`)는 꺼져 있고, 실 CLI 는 이용 조건 확인 전에는 돌지 않게 막아 두었습니다(아래).

**상주 실행(`serve --jobs`)**:
- **시작**: 홈 잠금 `locks/jobs.lock`(OS 파일 잠금 — 프로세스가 강제로 죽어도 OS 가 풀어 다음 시작을 막지 않습니다) → 장치 확인(`GET /api/imports/device`). 이미 다른 `serve --jobs` 가 돌고 있으면 종료 코드 1, 토큰이 없거나 거절·폐기면 종료 코드 3 으로 CLI 를 부르지 않고 끝납니다. 서버에 닿지 못하면 30초부터 최대 15분까지 늘려 기다리며 다시 확인합니다.
- **끝내기**: 첫 Ctrl+C·SIGTERM = 새 작업을 받지 않습니다. 실행 중 작업이 있으면 최대 30초 동안 완료·결과 전송을 기다립니다(작업이 없으면 바로 끝). 30초를 넘기거나 신호가 한 번 더 오면 CLI 와 그 하위 프로세스를 함께 끝내고(종료 확인) 멈춥니다. 서버에는 임대 갱신이 없어, 기다리는 동안도 처음 받은 5분 임대 안에서만 결과가 받아집니다.
- **끊긴 실행**: 끝났는지 모르는 실행은 실패로 보내지 않습니다 — 서버가 임대 만료 뒤 「확인 필요」로 남기고 다시 실행하지 않습니다. 다시 시작해도 그 작업을 다시 받거나 CLI 를 다시 부르지 않습니다.
- **출력**: 한 줄에 JSON 하나 — 작업 ID·종류·결과 코드·HTTP 상태·오류 코드·걸린 시간만. 입력·결과·프롬프트·토큰·서버 주소·CLI 출력·예외 문구는 쓰지 않습니다(예외는 클래스 이름만).
- **폴 주기**: 정상 = 롱폴 30초(소켓 여유 포함 최대 45초, `jobs.MAX_POLL_PERIOD_SEC`). CLI 실행 중(최대 5분)·서버 오류 대기(최대 15분)·429(최대 1시간) 동안은 폴하지 않습니다.

동작:
- **받기**: `GET /api/device/jobs?wait=30` 롱폴. 폴링 시작 간격 15초 이상(장치 분당 4). 서버가 429 를 주면 `Retry-After`(없으면 60초, 최대 1시간)를 지키고, 서버 오류·스위치 꺼짐·네트워크 오류면 30초부터 최대 15분까지 늘려 기다립니다. 토큰이 거절되면(401·폐기) 멈춥니다.
- **임대**: 작업마다 서버가 준 임대 세대를 입력 조회(`…/input?lease_generation=N`)·결과·실패에 그대로 싣습니다. 임대는 5분입니다. 서버가 409(`JOB-LEASE`·`JOB-VERSION`)나 410(`JOB-GONE` — 만료·삭제·취소)을 주면 그 작업을 버리고 다시 실행하지 않습니다.
- **결과 전송**: 연결이 끊기면 **같은 내용(같은 결과 버전)** 으로 다시 보냅니다. 모델은 다시 돌리지 않습니다. 429 면 임대가 남아 있는 동안만 `Retry-After` 를 지켜 다시 보냅니다. 끝내 못 보내면 버리고, 서버가 임대 만료 뒤 「확인 필요」로 남깁니다(중복 실행 없음).
- **실패 전송**: 사유 코드 하나만 보냅니다 — `output-not-json`·`output-shape`·`result-shape`·`timeout`·`cli-exit`·`login`·`input-too-large`. 입력·모델 출력·오류 문구는 보내지 않습니다.
- **입력 제한**: 8,000 코드포인트 **그리고** UTF-8 32KiB. 넘으면 실행하지 않고 `input-too-large` 로 끝냅니다.
- **동시 1**: 한 프로세스는 한 번에 작업 하나, 한 홈에는 작업 프로세스 하나(잠금 `locks/jobs.lock` — 예약 실행의 `run` 잠금과 다른 이름이라 서로 막지 않습니다).
- **CLI 격리**: `--tools ""` · `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` · `--setting-sources project` · `--permission-mode dontAsk` · `--max-turns 1` · `--output-format json`, 같은 대화는 `--resume`. 최소 환경변수, 빈 작업 폴더(`jobs-work/`), 입력은 표준 입력으로만. 토큰·HMAC 키·대응표는 넘기지 않습니다.
- **실 CLI 차단**: 환경변수 `MYCRM_JOBS_ALLOW_REAL_CLI=1` 이 없으면 실 CLI 어댑터를 만들 수 없습니다. 시험은 `tests/fake_claude.py` 만 씁니다.

**대화 정리(쌓기 단계, `stack.py` — kind `converse`)**:
- **정의 스냅샷**: 입력을 받은 뒤 `GET /api/device/jobs/<id>/definitions?lease_generation=N` 을 한 번 받아 그 작업 동안 고정합니다(모델을 다시 돌려도 다시 받지 않음). 연결이 끊기면 한 번 더 받고, 서버가 작업을 줄 때 알려 준 정의 버전과 다르면 실행하지 않습니다.
- **모델에게 주는 것**: 정의 요약(정의 ID·칸·관계·원천 ID 체계 — 보호 칸·연결 칸 제외)·`stack/1` 꼴·내용 제한·대상 후보 표(정의 응답의 `candidates` — 내 항목 id·code·제목·stage ≤500, 사람 id·별칭·출처 id·제목 각 ≤200; 이 표의 id 를 `explicit_id` 로, 표에도 입력에도 없는 대상은 `unresolved`)·입력(재정리면 원 결과 문단 + 고친 글 + 뺄 변경 + 막힌 질문의 답). 전부 표준 입력으로만, 입력은 맨 끝에 「데이터」로 둡니다.
- **검증**(통과해야만 전송): 문단(units) ≤ 40 · 변경(changes) ≤ 60 · 정리 글 ≤ 4,000자 · 요청 전체 ≤ 64KiB · ID 중복 없음 · 의존(depends_on)은 있는 변경만, 순환 없음 · 정의에 있는 칸·관계만 · 대상·연결 근거는 `source_id`(정의의 원천 ID 체계)·`explicit_id`·`inferred`·`unresolved` 넷 중 하나(근거 없는 연결·날짜·출처·비슷한 문장 연결 = 거부) · 확정·판단·stage·인용·한도·보호 칸 같은 서버 관리값 = 거부 · 모든 변경은 정확히 한 문단에 속함(정리 글에 안 보이는 변경 금지) · 연결 칸(사람·출처·축 등)은 `fields` 가 아니라 `links` 로만, 사람·출처 연결은 `explicit_id` 만 · 정리 글·칸 값에 URL·이메일·로컬 경로 금지(서버와 같은 규칙). 근거 유형은 권한이 아닙니다 — 서버가 다시 검사하고, 추정은 확인 카드에, 미해결은 막힘으로 갑니다.
- **보내는 꼴**: `{lease_generation, envelope:{contract:"stack/1", job_id, input_version, definitions_version, result_version, edit_generation, parent_result_version}, units, changes, blocked, model_meta}`. 봉투는 PC 가 만들고 모델은 만들지 않습니다.
- **다시 돌리기**: 출력이 JSON 이 아니거나 계약을 어기면 CLI 를 **한 번만** 다시 돌립니다(같은 `--resume`). 임대가 1분+여유 이상 남았을 때만. 그래도 안 되면 `result-shape`(또는 `output-not-json`) 로 끝냅니다. 로그인·CLI 종료 오류는 다시 돌리지 않습니다. 작업당 시도(`attempts`)와 실제 재실행(`cli_retries`)은 따로 셉니다.
- **서버 응답**: 입력·정의 조회가 요청 속도 한도(429)에 걸리면 임대 안에서 `Retry-After` 를 지켜 다시 받습니다(서버가 처리 전에 거절하므로 안전). 서버가 결과를 다시 검사해 거절하면(400 `CONTRACT-INVALID` — 예: 없는 항목을 대상으로) 모델을 다시 돌리지 않고 바로 `result-shape` 실패로 끝냅니다(5분 기다려 「확인 필요」가 되지 않게). 서버가 409(정의 바뀜 `JOB-DEFS`·버전·임대)를 주면 버립니다.
- **같은 대화 한 번에 하나**: 같은 대화(session_ref)의 CLI 는 동시에 돌지 않습니다. 앞 실행이 남아 있으면 이 작업 임대 안(최소 1분 실행 시간을 남기고)에서 기다리고, 못 기다리면 입력도 받지 않고 넘깁니다(서버가 임대 만료 뒤 「확인 필요」로 남김).
- **끝났는지 모를 때**(CLI 시간 초과): 실패를 보내지 않고 그 대화를 임대 만료(5분)까지 잠가 둡니다 — 서버는 「확인 필요」로 남기고, 같은 대화가 겹쳐 이어지지 않습니다.

PC 에 남는 것: `jobs-state.json`(현재 사용자만 읽기·쓰기, 판 2 — 판 1 파일은 읽을 때 올림) = 진행 중 작업의 임대 세대·대화 참조·임대 만료 시각 · 날짜별 시도 수·재실행 수 · 대화 참조 → CLI 세션 ID 대응. **입력·결과·프롬프트·정의 본문은 저장하지 않습니다**(메모리에서만 다룸). CLI 세션 ID 는 서버로 보내지 않습니다. 서버에 가는 결과의 모델 정보는 도구 이름·모델 이름·걸린 시간·CLI 실행 횟수뿐입니다.

시험:
```bash
python3 -m unittest agent.tests.test_jobs        # 표준 라이브러리 스텁 서버(포트 0, JOBS_STUB_PORT 로 고정 가능) · 가짜 CLI
python3 -m unittest agent.tests.test_serve       # 상주 실행 — 잠금·인증·신호·유예·자식 그룹 종료(FAKE_MODE=hang)·전달 재개
python3 -m unittest agent.tests.test_stack       # 쌓기 단계 — 계약 검증 + 시나리오(FAKE_STACK: ok·contract-bad·forbidden-field·
                                                 #   unref-link·inferred·blocked·restack·cycle·oversize) + 세션 직렬화
```
실 서버로 다시 확인할 때만(로컬 주소·`crm_test_*` DB 가 아니면 건너뜀, 토큰은 환경변수로만):
```bash
JOBS_LIVE_URL=http://127.0.0.1:<포트> JOBS_LIVE_TOKEN=<시험 장치 토큰> [JOBS_LIVE_TOKEN_B=<같은 사용자 두 번째 장치>] \
JOBS_LIVE_DB=postgresql://localhost/crm_test_<이름> python3 -m unittest agent.tests.test_jobs.LiveApiTest
```
실시험은 상태 읽기와 「서버 시각 경과」 흉내(만료 시각을 앞당김)에만 `psql` 을 쓰고, 판정은 전부 API 를 거칩니다. 장치 폴링 한도(분당 4)를 쓰므로 1분 안에 다시 돌리면 첫 폴이 429 를 받을 수 있습니다.

## board 이전 명세 생성기 (`board_manifest.py`, 원작자 PC 전용)

board 정본 마크다운에서 AI 검토표와 이전 명세(`board-migration/1`)를 만듭니다. 입력 경로는 전부 로컬 설정 파일(JSON)로 받고, 서버엔 검토표를 올리지 않습니다. 서버 `migrate_cli.py` 는 운영 반영 경로에서 은퇴해 합성 시험 DB(`crm_test*`)용으로만 남았습니다. 운영 이관은 아래 「실자료 이관 업로더」 절의 `migrate` 업로더로 올리고 웹 이관 화면에서 확인·반영합니다(계약 `board-migration/2`).
```bash
python3 agent/board_manifest.py sheet    --config CFG --state-dir DIR --out SHEET.md
python3 agent/board_manifest.py build    --config CFG --state-dir DIR --sheet SHEET.md --out MANIFEST.json \
                                         --target-user-id U --source-instance-id S --reviewed-at 2026-10-20T21:00:00+09:00
python3 agent/board_manifest.py validate MANIFEST.json [--config CFG --state-dir DIR --sheet SHEET.md]
```
`--source-instance-id` 는 서버 `migrate_cli.py init` 이 출력한 ID 입니다. 고객사 원문(D 본문·E·W)을 두는 폴더는 설정의 `forbidden_roots`(설정 파일 기준 상대 경로·`~/`·절대 경로) 에 직접 적습니다 — 코드에 박아 둔 경로는 없고 기본값은 비어 있습니다. 그 아래 파일은 심볼릭 링크로 가리켜도 읽지 않습니다. 예시 설정은 `agent/tests/fixtures/board/config.example.json`. 검토표의 차단 항목(`⚠️AI` 줄·`(AI)` 절·URL·경로 꼴 줄·D 색인 제목·craft 이슈 키)을 전부 골라야 명세가 나옵니다. 참조는 정확한 판(`{original_id, revision}`)으로 적습니다.

## 실자료 이관 업로더 (`migrate`, `board-migration/2`)

검토를 끝낸 항목 명세(JSONL)를 서버 이관 plan 으로 올립니다. 확인·체크·반영은 웹 이관 화면에서만 합니다. 이 명령은 올리기·상태·취소·영수증 대조만 합니다. 서버가 이관 스위치와 허용 목록으로 켠 계정만 씁니다.

```bash
# 1) 웹 이관 화면에서 토큰을 발급해 표준 입력으로 넣는다(화면·명령줄·로그에 남지 않는다)
python3 -m agent migrate login   --server https://crm.example.invalid --token-stdin < 토큰을_담은_파일
#    (또는 브라우저 로그인으로 받는다 — 토큰이 파일·화면을 거치지 않는다)
python3 -m agent migrate login   --server https://crm.example.invalid --browser
# 2) 검증 → plan 만들기 → 청크 업로드 → seal → dry-run 요약(plan_id 출력)
python3 -m agent migrate stage   items.jsonl --server https://crm.example.invalid --source-instance pc-home-1
python3 -m agent migrate status  mp_0123456789abcdef01234567 --server https://crm.example.invalid
python3 -m agent migrate cancel  mp_0123456789abcdef01234567 --server https://crm.example.invalid
# 3) 웹에서 반영한 뒤 영수증을 같은 입력 파일과 대조
python3 -m agent migrate receipt mp_0123456789abcdef01234567 --server https://crm.example.invalid --verify items.jsonl
python3 -m agent migrate logout  --server https://crm.example.invalid
```

- **토큰**: 이관 전용(`mig_mt_…`, 발급 뒤 14일 만료)입니다. 연결 장치 토큰과 다릅니다. Keychain(Windows 는 Credential Manager)의 계정 `migration-token:<서버 호스트>` 에 둡니다. `logout` 은 로컬만 지웁니다. 서버 쪽 폐기는 웹에서 합니다. 새 이관 토큰을 받아도 앞 토큰은 새 토큰이 서버에서 처음 인증될 때 폐기됩니다(그 전까지는 앞 토큰도 유효). 데스크톱 앱이 대화 발급으로 받은 이관 토큰은 앱이 `migrate login --token-stdin` 으로 같은 자리에 넣습니다.
- **입력**: 한 줄에 계약 항목 하나입니다. `original_id` 는 꼭 있어야 합니다. 권장 공식은 `'o_' + sha256(source_instance + '\n' + 원천 경로 + '\n' + anchor)[:32]` 입니다. 비어 있는 값은 이렇게 채웁니다: `source_instance` 는 `--source-instance` 값, `content_hash` 는 정규화한 본문(출처는 `source.name`)의 SHA-256, `source_revision` 은 `'v_' + sha256(JCS(항목 − source_revision))[:32]` 입니다. 정규화 규칙은 서버와 같은 벡터 파일(`server/contract/imports/vectors/board-migration-2-normalize.json`)로 묶여 있습니다.
- **올리기 전에 로컬에서 거절하는 것**: JSON 규칙 위반(중복 키·실수·NaN), 사용자 필드(`owner`·`user_id` 등 8개), `original_id` 없음·형식 틀림·중복, 모르는 `unit_kind`, 적힌 `content_hash` 가 다시 계산한 값과 다름, 본문 64KB·줄 96KB·항목 200개·합계 2MB 초과. 이 경우 서버에 아무것도 보내지 않습니다. 그 밖의 계약 구조 오류는 서버가 업로드 때 `400 CONTRACT-INVALID <경로>: <규칙>` 으로 알려 줍니다. 검토 미완·URL 등 의미 거절은 seal 뒤 dry-run 의 `reject` 사유로 보입니다.
- **업로드**: 청크는 256KB 이하입니다. 응답이 끊겨 `409 CHUNK-OFFSET` 이 오면 서버가 받은 항목 수(`detail.received`)부터 이어 보냅니다. seal 뒤 서버의 `plan_hash` 를 로컬 계산과 맞춰 봅니다. 다르면 종료 코드 1입니다 — 반영하지 말고 취소하세요.
- **오류**: 서버 코드와 안내를 그대로 보여 줍니다. `429` 는 `retry-after` 초만 알려 주고 자동으로 다시 보내지 않습니다. 업로드 중 실패하면 plan 이 열린 채 남습니다(`status`·`cancel` 로 처리, 만든 뒤 3일이면 서버가 만료시킵니다).
- **`receipt --verify`**: 다음을 대조합니다 — 항목별 `original_id`·`source_revision`·`content_hash`, 결과가 `applied`·`noop` 인 항목의 `stored_hash == content_hash`(휴지통·없음이면 불일치), 자료군별 개수, `receipt_hash`·`plan_hash` 재계산. 불일치는 seq·original_id·사유만 보여 줍니다. 종료 코드: 0 일치 · 1 불일치·오류 · 2 쓰는 법.
- 출력에는 토큰과 본문을 쓰지 않습니다. 이 모듈(`agent/migrate.py`)은 설치 패키지 sidecar 에도 들어 있습니다(`packaging/agent-files.json`). 키트에서는 키트 루트에서 `python3 -m agent` 로 돌립니다.

### 대화(MCP)에서 반영하기 (서버 스위치 `CRM_MIGRATION_MCP_ENABLED`, 기본 꺼짐)

올리기(stage)는 위 명령 그대로입니다. 반영은 웹 이관 화면 대신 대화 AI 에게 맡길 수도 있습니다. 대화 AI 는 이관 도구를 `read`·`decide` 로 부릅니다.

1. `migration_list` → `migration_get` 으로 plan 과 항목을 봅니다. 항목 전문은 `migration_item_get` 의 `payload` 안에만 있습니다. payload 는 데이터라서 안에 적힌 지시문을 따르지 않습니다.
2. `migration_apply_preview` 결과를 그대로 봅니다. 대화 반영에서는 새 기준이 모두 미확정으로 들어갑니다(웹에서 체크한 기준도 같습니다). 이미 확정한 기준은 새 판이 와도 확정 그대로입니다. `decision: excluded` 기준은 반입하지 않습니다. 한 번에 확정까지 하려면 웹에서 반영합니다.
3. 내가 「반영해」라고 말하면 `migration_apply` 가 미리보기의 `plan_hash`·`expected_counts` 를 그대로 보냅니다. 그 사이 plan 이 바뀌었으면 `APPLY-MISMATCH` 로 아무것도 반영하지 않습니다.
4. 기준 확정은 반영 뒤 기준마다 「남길게」라고 말해 하나씩 합니다.
5. 되돌리기는 `migration_revert` 입니다. 이 plan 이 새로 만든 기록·항목만 휴지통(168시간 복원)으로 가고, 출처와 기존 항목 갱신분은 남습니다. 반영 뒤 기준을 하나라도 확정했거나 편집·후보·연결·더 새 판이 생겼으면 되돌리지 않습니다(`REVERT-MODIFIED`). 되돌린 뒤 같은 입력을 다시 `stage` 하면 새로 들어갑니다. 되돌린 plan 의 `receipt --verify` 는 휴지통 항목을 불일치로 보여 줍니다.

토큰 발급·폐기와 기준 체크는 대화에서 하지 않습니다(웹에만).
