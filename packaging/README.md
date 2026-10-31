# PC 앱 릴리스 절차

PC 앱(`desktop/`)과 함께 들어가는 연결 장치(`agent/`)를 GitHub Release로 내보내는 절차다. 설치 파일은 GitHub Release asset에서만 받는다.

**로컬 빌드를 Release에 수동 업로드하지 않는다.** Release asset은 태그 실행의 `release` job만 올린다.

## 처음 한 번

- repo secret `CRM_SCRUB_EXTRA`(쉼표 구분 패턴)를 등록한다. 태그 실행은 이 값으로 풀린 앱(asar 내용 포함)을 검사한다. 값이 비면 태그 실행이 실패한다.

## 릴리스마다

1. `desktop/package.json`의 `version`을 올린다. 워크플로가 빌드 인자·태그 검사에 이 값을 읽는다.
2. PR을 main에 merge한다. merge는 서버 재배포이기도 하다.
3. main의 그 커밋에 `v<버전>` 태그를 push한다(예: 버전 `0.1.2` → 태그 `v0.1.2`).
   - 태그와 `version`이 다르면 빌드가 실패한다.
   - 태그 커밋이 `origin/main`에 없으면 `release` job이 멈춘다.
4. `Desktop installers` 워크플로가 끝나면 draft Release가 생긴다. 검토한다.
   - asset 4개: `MyCRM-mac-arm64.dmg`·`MyCRM-mac-x64.dmg`·`MyCRM-win-x64.exe`·`SHA256SUMS.txt`
   - 본문: `packaging/release-notes.md` 그대로
5. draft asset으로 깨끗한 Mac·Windows에서 설치·첫 실행 경고·연결·동기화를 실측한다. macOS에서 「손상되었기 때문에 열 수 없습니다」가 나오면 publish하지 않는다.
6. publish한다. prerelease로 표시하지 않는다(「최신」 링크와 앱 업데이트 확인이 prerelease를 무시한다).

## 첫 publish 뒤 한 번

- 서버 환경변수 `CRM_DOWNLOAD_PUBLIC=1`을 켠다. 그 전까지 `/download`는 「준비 중」만 보인다.

## 파일 이름

- 「최신」 링크: `https://github.com/WJY-ador/personal-mycrm/releases/latest/download/<고정 이름>`
- electron-builder 산출물 이름(`MyCRM-<버전>-<os>-<arch>`)은 그대로 두고, `release` job이 고정 이름으로 바꾼 뒤 `SHA256SUMS.txt`를 다시 만든다. `latest*.yml`·`.blockmap`은 workflow artifact에만 남고 Release에는 올리지 않는다.

## 서명

- mac은 ad-hoc 서명(`mac.identity: "-"`, hardened runtime)이다. `packaging/verify_bundle.py`가 `codesign --verify --deep --strict`로 앱 전체 서명을 확인한다. Apple 공증은 없다.
- Windows는 서명하지 않는다. 첫 실행 때 SmartScreen 경고가 뜬다.
- 설치 경고 안내의 정본은 `packaging/release-notes.md` 하나다. 실측 결과로 이 파일을 고친다.
