# PC 앱 릴리스 절차

PC 앱(`desktop/`)과 함께 들어가는 연결 장치(`agent/`)를 GitHub Release로 내보내는 절차다. 설치 파일과 앱 내 업데이트 파일은 GitHub Release asset에서만 받는다.

**로컬 빌드를 Release에 수동 업로드하지 않는다.** Release asset은 태그 실행의 `release` job만 올린다.

## 처음 한 번

- repo secret `CRM_SCRUB_EXTRA`(쉼표 구분 패턴)를 등록한다. 태그 실행은 이 값으로 풀린 앱(asar 내용 포함)을 검사한다. 값이 비면 태그 실행이 실패한다.
- mac 릴리스 서명 인증서를 만들고 repo secret 둘을 등록한다. 아래 서명 절의 인증서 만들기를 따른다.
  - `MAC_SIGN_P12_BASE64`: 인증서와 개인 키를 담은 `.p12` 파일의 base64
  - `MAC_SIGN_P12_PASSWORD`: 그 `.p12`의 암호
  - 둘이 비면 태그 실행과 수동 실행의 mac job이 실패한다.

## 릴리스마다

1. `desktop/package.json`의 `version`을 올린다. 워크플로가 빌드 인자와 태그 검사에 이 값을 읽는다.
2. PR을 main에 merge한다. merge는 서버 재배포이기도 하다.
3. main의 그 커밋에 `v<버전>` 태그를 push한다(예: 버전 `0.1.2`이면 태그 `v0.1.2`).
   - 태그와 `version`이 다르면 빌드가 실패한다.
   - 태그 커밋이 `origin/main`에 없으면 `release` job이 멈춘다.
4. `Desktop installers` 워크플로가 끝나면 draft Release가 생긴다. 검토한다.
   - asset 11개. 목록의 정본은 `desktop/scripts/release-assets.cjs names`이고, `release` job이 draft의 asset이 이 목록과 같은지 검사한다.

     | 쓰임 | 파일 |
     |---|---|
     | 내려받기(고정 이름) | `MyCRM-mac-arm64.dmg`, `MyCRM-mac-x64.dmg`, `MyCRM-win-x64.exe` |
     | 앱 내 업데이트 피드 | `latest-mac.yml`(arm64와 x64 병합), `latest.yml` |
     | 앱 내 업데이트 파일 | `MyCRM-mac-arm64.zip`, `MyCRM-mac-x64.zip` |
     | 차분 다운로드 | `MyCRM-mac-arm64.zip.blockmap`, `MyCRM-mac-x64.zip.blockmap`, `MyCRM-win-x64.exe.blockmap` |
     | 체크섬 | `SHA256SUMS.txt` |

   - 본문: `packaging/release-notes.md` 그대로
5. draft asset으로 깨끗한 Mac과 Windows에서 설치, 첫 실행 경고, 연결, 동기화를 실측한다. macOS에서 "손상되었기 때문에 열 수 없습니다"가 나오면 publish하지 않는다.
6. publish한다. prerelease로 표시하지 않는다. "최신" 링크와 앱 업데이트 확인이 prerelease를 무시한다.

## 첫 publish 뒤 한 번

- 서버 환경변수 `CRM_DOWNLOAD_PUBLIC=1`을 켠다. 그 전까지 `/download`는 "준비 중"만 보인다.

## 파일 이름

- "최신" 링크: `https://github.com/WJY-ador/personal-mycrm/releases/latest/download/<고정 이름>`
- electron-builder 산출물 이름(`MyCRM-<버전>-<os>-<arch>`)은 그대로 둔다. `release` job이 모든 산출물 이름에서 `-<버전>`을 뺀다. 내려받기 고정 이름 셋이 이 규칙으로 나온다.
- `release` job은 `latest-mac.yml`과 `latest.yml` 안의 파일 이름도 같은 규칙으로 고쳐 쓴다. 올리기 전에 두 피드가 가리키는 모든 파일이 같은 이름의 asset으로 있고 sha512와 크기가 맞는지 검사한다. 같은 파일을 두 이름으로 올리지 않는다.
- 그 뒤 `SHA256SUMS.txt`를 다시 만든다.

## 서명

### mac

- 태그 push와 수동 실행(workflow_dispatch)은 자가 서명 릴리스 인증서로 앱 전체(연결 장치 sidecar 포함)를 서명한다. 서명 함수는 `desktop/scripts/mac-sign.cjs`다. 서명의 designated requirement는 `identifier "io.mycrm.desktop" and certificate root = H"<인증서 SHA-1>"`이고 버전이 바뀌어도 같다. 앱 내 업데이트(Squirrel.Mac)는 새 판이 이 요구를 만족할 때만 설치한다.
- 이 빌드에만 패키지된 `package.json`에 `mycrmMacUpdater: true` 표식을 넣는다. 표식이 있는 mac 앱만 앱 안에서 받아 설치한다.
- pull_request 빌드는 secret이 등록돼 있어도 ad-hoc 서명(`mac.identity: "-"`)으로 만들고 표식을 넣지 않는다. 이 판은 앱 내 업데이트를 하지 않고 릴리스 페이지로 안내한다.
- 빌드 뒤 `desktop/scripts/check-build.cjs`가 서명 방식과 표식의 짝, 앱의 `Resources/app-update.yml`, 업데이트 피드를 검사한다. 표식이 있는 ad-hoc 판은 실패한다. 이어서 `packaging/verify_bundle.py`가 `codesign --verify --deep --strict`로 앱 전체 서명을 확인하고, 서명된 sidecar를 hardened runtime으로 실행해 본다.
- Apple 공증은 없다.

### mac 인증서 만들기 (처음 한 번)

Homebrew의 OpenSSL 3 이상을 쓴다. macOS 기본 `/usr/bin/openssl`(LibreSSL)에는 `-legacy`가 없다. `-legacy` 없이 만든 `.p12`는 macOS `security import`가 읽지 못한다.

```sh
OPENSSL=/opt/homebrew/bin/openssl
cat > mycrm-sign.cnf <<'EOF'
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = MyCRM Release Signing
O = MyCRM
[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
EOF
"$OPENSSL" req -x509 -newkey rsa:3072 -nodes -days 3650 -config mycrm-sign.cnf \
  -keyout mycrm-sign.key -out mycrm-sign.pem
"$OPENSSL" pkcs12 -export -legacy -name "MyCRM Release Signing" \
  -inkey mycrm-sign.key -in mycrm-sign.pem -out mycrm-sign.p12   # 암호를 묻는다
base64 -i mycrm-sign.p12 | gh secret set MAC_SIGN_P12_BASE64
gh secret set MAC_SIGN_P12_PASSWORD                              # 위 암호를 붙여 넣는다
```

- `O`(조직) 줄을 지우지 않는다. 없으면 designated requirement가 `certificate leaf`로 바뀌고 `check-build.cjs`가 빌드를 멈춘다.
- 인증서는 로그인 keychain에 넣지 않는다. CI가 실행마다 임시 keychain에 넣고 끝나면 지운다.
- **`.p12`와 그 암호를 백업한다. 필수다.** 깔린 앱은 같은 인증서로 서명한 판만 업데이트로 받는다. 인증서를 잃거나 새로 만들면 이미 깔린 mac 앱 전부가 앱 내 업데이트를 못 하고, 사용자가 새 판을 한 번 직접 설치해야 한다. 백업은 암호화해서 이 Mac 밖에도 한 벌 둔다.
- 백업한 뒤 평문 개인 키 `mycrm-sign.key`는 지운다. `.p12`가 키를 담고 있다.

### Windows

- 서명하지 않는다. 첫 실행 때 SmartScreen 경고가 뜬다.
- 앱 내 업데이트는 `latest.yml`의 sha512로 받은 파일을 확인한다. 코드 서명 검증은 없다.

### 설치 경고 안내

- 설치 경고 안내의 정본은 `packaging/release-notes.md` 하나다. 실측 결과로 이 파일을 고친다.

## 알려진 한계

- 0.1.x 판과 ad-hoc 서명 판(PR 빌드 포함)에서는 앱 내 업데이트로 넘어가지 못한다. 앱 내 업데이트가 든 릴리스 인증서 판을 한 번 직접 설치해야 한다. 그 뒤부터 앱 안에서 업데이트한다.
- mac은 처음 설치할 때의 Gatekeeper 경고가 남는다. 자가 서명은 Apple 공증을 대신하지 않는다. 경고를 없애는 길은 유료 Apple Developer ID와 공증뿐이다.
- mac 인증서는 바꿀 수 없다. 바꾸면 위 백업 항목과 같이 업데이트 사슬이 끊긴다.
- mac 앱은 Apple Team ID가 없어 Keychain이 업데이트한 판을 다른 앱으로 본다. Electron safeStorage로 저장한 값(동의 서명 키)을 업데이트한 판이 읽을 때 Keychain 허용 창이 뜬다(시험 앱 실측). 연결 토큰(`security` 명령으로 저장)은 같은 실측에서 창 없이 읽혔다.
