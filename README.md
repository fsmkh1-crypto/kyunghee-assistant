# Kyunghee Assistant

Windows productivity timer and virtual secretary.

## Current development target

`0.4.0-alpha`

The 0.4 line is focused on correctness before real-world testing.

## Desktop app

Development is focused on the Windows desktop app. `RUN.cmd` launches the integrated desktop UI during development. The **Desktop Package** workflow builds a standalone `KyungheeTimer.exe` package that does not require Python on the user's PC.

The earlier `android-prototype/` is retained only as inactive design history and is not a current development target.

The settings page now persists and applies:

- Windows sign-in startup
- always-on-top mode
- break reminder on/off
- workday reminder on/off
- wind-down, leave, strong-leave, and late-leave times

User preferences are stored in `%APPDATA%\KyungheeAssistant\settings.json`.

### Core timer behavior

- 60 minutes of continuous active use triggers a break reminder.
- Snooze delays the reminder by exactly 5 minutes, repeatedly.
- Manual away starts immediately and ends only on a later keyboard/mouse input.
- The click that starts manual away is explicitly ignored as a resume signal.
- A scheduler/sleep gap over 90 seconds is classified as away, never active.
- If there is no keyboard/mouse input for 5 minutes, the **entire no-input interval** is retroactively reclassified as away.
  - 4m59s idle followed by input remains active use.
  - 5m00s idle becomes 5m00s away.
- App downtime over 60 seconds breaks continuous-session continuity on restart.
- Untracked app downtime is not invented as active or away time.
- Daily statistics roll over at midnight without resetting the global continuous session or break schedule.
- Only the portion of a cross-midnight session that occurred today can become today's longest-continuous statistic.

### Workday-aware behavior

Default pattern:

- usual arrival: around 08:40
- wind-down begins: 17:00
- leaving-work mode: 17:30
- stronger leave-work prompts: 18:00+
- late-work nagging: 18:30+
- hard warning after 9 hours of actual active use

Once leaving-work mode is active, the assistant should stop encouraging additional work and instead encourage wrapping up.

### Reliability

- single-instance protection through a Windows named mutex
- atomic state writes with process-specific temporary files
- corrupt JSON is preserved as a `.corrupt` file before resetting state
- rotating application logs
- Tk UI commands from the tray are marshalled through a queue
- deterministic timer-engine tests use injected clock/wall/idle providers and run on Linux CI

## Privacy

The app does **not** record key contents, window titles, clipboard data, browser data, or typed text.
It only reads last-input timing metadata through Windows `GetLastInputInfo`.

## External review

See [`REVIEW_FOR_CLAUDE.md`](REVIEW_FOR_CLAUDE.md).
The repository is intentionally public so external reviewers can audit the current `main` branch directly.

## Status

Not yet a production release. The next gate is:

1. green deterministic CI
2. external code review of the current `main` branch
3. finalized character/image assets
4. Windows real-world testing
# 선택형 AI 대사·대화 작업 사본

검토용은 별도 폴더에 풀고 `RUN_AI_REVIEW.cmd`로 실행해 주세요. 이 실행기는 데이터를 `%LOCALAPPDATA%/KyungheeTimer_AI_Review/KyungheeAssistant`에 분리합니다. 기존 타이머는 트레이에서 종료한 뒤 실행해 주세요. 원래 `RUN.cmd`와 `python desktop_gallery_final.py` 진입점은 그대로이며 기존 앱 데이터 경로를 사용합니다. 타이머·기록 파일 형식은 유지됩니다.

- 캐릭터 머리 위 말풍선의 **대화**를 누르면 짧은 텍스트 대화 창을 엽니다. 대화와 **오늘 마무리**는 타이머 상태를 직접 바꾸지 않습니다.
- 설정 아래 **AI 설정**에서 API 키를 입력하고 ON으로 적용합니다. 기본값은 OFF이며 키가 없거나 호출에 실패하면 기존 로컬 대사를 사용합니다.
- 키 입력은 마스킹됩니다. 기본적으로 이번 실행 중에만 보관하며, **키 기억**을 선택한 Windows에서만 현재 계정의 DPAPI로 암호화합니다. 일반 설정 JSON이나 로그에는 키를 넣지 않습니다. **키 지우기**로 세션·저장 키를 지울 수 있습니다.
- **연결 테스트**는 실제 OpenAI API 요청입니다. 본인의 MIN 조직 프로젝트 키와 API 사용 가능 여부를 확인해 주세요. 이 작업에서는 실제 키·크레딧을 확인하지 않았습니다.
- AI를 켜면 필요한 이벤트의 시각·사용량·자리비움·휴식·말투, 당일 이벤트 코드, 최근 AI 대사와 전송한 대화를 OpenAI로 보냅니다. 로컬·커스텀 대사는 중복 검사에만 쓰며 보내지 않습니다. 대화·당일 AI 기억은 메모리에만 있고 날짜가 바뀌거나 앱을 종료하면 사라집니다.
- **추가 세트 ZIP 가져오기**는 10개 역할이 완비된 번호 PNG 세트를 추가합니다. 동일한 파일은 유지하고, 기존 파일과 다르면 전체 가져오기를 중단합니다. 원본 ZIP·정본 이미지는 덮어쓰지 않습니다. 분할 배포본 `.part01/.part02`는 이 기능의 입력이 아닙니다.

Pretendard 글꼴과 재배포 라이선스를 `assets/fonts`에 포함했습니다. 글꼴은 앱 프로세스에서만 등록합니다. 기존 사용자가 저장한 크기·색은 유지하며 새 설치의 대사 기본 크기는 13입니다.

검증 범위와 남은 확인은 `AI_HANDOFF.md`, 현재 작업 상태는 `PROJECT_STATE.md`를 참고해 주세요.
