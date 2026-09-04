# Phase 4 New Conversation Handoff

Use this as the starting prompt for a new ChatGPT conversation.

---

깃허브 `fsmkh1-crypto/kyunghee-assistant`의 `ui/dark-kyunghee-redesign` 브랜치에서 작업을 이어가.

먼저 반드시 다음 순서로 현재 상태를 확인해:
1. `PROJECT_PHASES.md`를 읽는다.
2. `PHASE4_HANDOFF.md`를 읽는다.
3. PR #3 `UI: dark Kyunghee timer redesign`을 확인한다.
4. 현재 브랜치 HEAD를 확인한다.
5. `desktop_compact.py`, `desktop_app.py`, `settings.py`, `asset_manager.py`의 현재 구조를 파악한다.
6. `main`은 현재 데스크톱 UI 기준으로 오래된 브랜치이므로 사용하지 않는다.

현재까지 중요한 고정사항:
- Windows용 frameless transparent Tkinter 위젯이다.
- 현재 데스크톱 진입점은 `desktop_compact.py`다.
- `assets/`의 승인된 경희 PNG는 canonical asset이다. 재생성하거나 교체하지 마라.
- Pretendard는 사용자 PC 설치를 전제로 한다. 폰트 파일을 번들하지 마라.
- 경희 이미지를 짧게 클릭하면 상세 화면, 드래그하면 창 이동이다.
- 메시지를 클릭하면 문구가 바뀐다.
- 시간/상태/메시지는 선택적으로 숨길 수 있다.
- 위젯 배율은 80~200%다.
- 위젯 배율과 글자 크기는 분리되어 있다. 글자 크기를 위젯 배율에 따라 같이 키우지 마라.
- 투명 컬러키 구조를 유지한다.
- 빈 투명 영역이 Windows에서 뒤쪽 창 클릭을 통과시키는 현재 동작을 사용자가 매우 좋아한다. 이 동작을 깨지 마라.
- `Ctrl+Shift+H` 글로벌 숨김/표시, 위치 저장, 멀티모니터 복구, topmost 옵션 등 Phase 1 동작은 이미 실사용 통과 상태다. 건드릴 때 회귀를 매우 조심한다.
- Phase 3은 완료 상태다. 배율/표시 토글/드래그/투명 클릭 스루/레이아웃을 불필요하게 다시 설계하지 마라.
- Phase 3 최종 레이아웃은 시계/상태 + 경희를 하나의 visible cluster로 보되, PNG 전체 박스가 아니라 실제 보이는 alpha silhouette 경계를 기준으로 배치한다.
- 시계/상태는 경희의 실제 보이는 왼쪽 경계에 약 6px 정도의 작은 시각 간격으로 붙는다. 배율별 간격표를 다시 만들지 마라.
- 메시지는 경희 바로 아래 기준으로 붙는다.

Phase 3 최종 관련 커밋:
- `f123574fdbeb0008f2c65b09d05fc0098b686049` — `Align clock to visible character silhouette`
- `c597157e6bec50c431104a92344b00fe786a9a30` — `Build visible-alpha cluster Phase 3 test package`
- `a6c44c0e75525b15d8e683ff7203c423fe05741b` — `Mark Phase 3 complete and prepare Phase 4 handoff`

Phase 3 최종 Windows 검증:
- workflow: `Build Phase 3 final test`
- run: `33845865572`
- compile/tests: PASS
- Windows build: PASS
- smoke test: PASS
- artifact: `kyunghee-timer-phase3-final-test`
- 사용자가 80%, 140%, 200% 실화면을 직접 확인하고 Phase 3을 종료해도 된다고 승인했다.

Phase 4는 현재 구현 중이다. 이미지 세트 저장 계층과 실제 compact runtime 연결까지 완료됐다.

Phase 4 목표:
상황/역할별 경희 이미지 시스템을 확장하되 기존 승인 이미지와 기존 단일 이미지 import/fallback을 깨지 않는다.

구현 우선순위:
1. 설정 화면 이미지 preview
2. preview 전용 cache/invalidation 마무리
3. 확장된 이미지 설정 UI의 Windows 실화면 검증
4. app-owned imported copies 저장 원칙 유지

작업 원칙:
- 먼저 현재 코드 구조와 설정 schema를 검토하고 Phase 4 설계를 짧게 정리한다.
- 큰 구조 변경이나 사용자 선택이 꼭 필요한 사안이 아니면 확인 질문으로 멈추지 말고 바로 구현을 이어간다.
- 임의로 UI 전체를 다시 디자인하지 않는다.
- 승인된 경희 이미지를 새로 그리거나 교체하지 않는다.
- 기존 단일 이미지 custom import/fallback과 canonical role resolution을 깨지 않도록 확장형으로 설계한다.
- Phase 1~3 기능 회귀를 막는 테스트를 같이 보강한다.
- Windows-specific 변경 후에는 tests/build/smoke를 돌린다.
- 실제 시각 확인이 필요한 경우에만 사용자에게 테스트본을 준다.
- Phase 4 작업 중 레이아웃 문제가 보이더라도 Phase 3의 visible-alpha cluster 원칙을 먼저 보존하고, 실제 회귀일 때만 최소 수정한다.

다음 작업은 현재 HEAD와 CI 상태를 확인한 뒤 설정 화면 이미지 preview부터 이어가.
