# Windows에서 별도 실행본 만들기

이 문서는 로컬 빌드 방법입니다. 소스 ZIP이나 빌드 키트는 완성된 Windows EXE가 아닙니다. 실제로 생성한 실행본인지, 어떤 검사를 통과했는지는 결과 폴더의 보고서로 확인하세요.

## 준비와 실행

1. 기존 승아 타이머를 트레이에서 종료하세요. 이전 2.1.5 폴더와 사용자 데이터는 그대로 두고, 이번 소스를 새 폴더에 풉니다.
2. 64비트 Windows Python 3.12 이상을 준비합니다. Tcl/Tk와 pip가 포함되어 있어야 합니다. [공식 Windows Python](https://www.python.org/downloads/windows/)을 사용할 수 있습니다.
3. `BUILD_WINDOWS.cmd`를 실행하거나 터미널에서 `python tools/build_windows.py`를 실행합니다. 기본 방식은 새 가상환경에 필요한 패키지를 다운로드합니다. 기존 Python의 설치 패키지는 바꾸지 않습니다.
4. 자동 GUI 검사 중에는 별도 임시 창이 뜹니다. 검사하는 동안 키보드와 마우스를 사용하지 마세요. 사용자 대화·설정·키 대신 별도 임시 프로필과 고정 입력으로 검사합니다.

인터넷 없이 빌드하려면 해당 Windows Python 버전과 x64에 맞는 Pillow·pystray·PyInstaller 및 모든 의존 wheel을 준비하고 `python tools/build_windows.py --wheel-dir C:\path\to\wheels`로 실행하세요. 이 옵션은 pip의 외부 인덱스 연결을 끕니다. Python 자체는 먼저 설치되어 있어야 합니다.

## 결과와 실패 구분

- 기본 결과 위치는 `dist/local-windows/SeungaTimer-버전-시각-고유값/`입니다. 매번 새 폴더를 만들고 이전 빌드나 ZIP을 덮어쓰지 않습니다. `--output-dir`로 결과 부모 폴더를 지정할 수 있습니다.
- 전체 테스트, EXE 패키징, 새 이미지 세트 기능을 포함한 4단계 배율 검사와 정상 시작 검사가 성공해야 전달용 ZIP을 만듭니다. 실패하면 새 폴더의 `BUILD_FAILED.txt`와 `logs/`를 확인하세요. 실패 중 만들어진 중간 EXE는 전달용 결과가 아닙니다.
- 한국어 IME 검사는 `passed`, `failed`, `unavailable`을 구분합니다. `unavailable`은 실제 한글 조합을 확인하지 못했다는 뜻이며 통과로 세지 않습니다. 실패한 IME 검사는 패키지 완성을 중단합니다.
- 성공한 ZIP에는 `SeungaTimer.exe`, `_internal`, 사용 안내, `BUILD_INFO.txt`, 소스 해시 목록, 의존 패키지 버전과 검사 보고서가 들어갑니다. ZIP 옆 SHA-256 파일로 전달 후 동일 파일인지 확인할 수 있습니다.

새 ZIP도 별도 폴더에 전부 풀고 `SeungaTimer.exe`와 `_internal`을 함께 두세요. 대화창 제목의 **2.1.6**을 확인하면 이전 실행본과 구분할 수 있습니다.

이 빌더는 Git 게시·외부 업로드·Release·병합을 하지 않으며 언어팩, IME 모드, PowerShell 실행 정책을 변경하지 않습니다. 자동 검사 통과와 사용자 PC의 실제 입력·다중 모니터·장시간 사용 검증은 별개입니다.
