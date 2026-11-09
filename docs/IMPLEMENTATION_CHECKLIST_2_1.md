# 승아 타이머 2.1 구현·검증 목록

기준: 배포 커밋 `15accd3`와 PR #4 대상 `66fb497`. 사용자가 독립 검수의 필수 복원, 결함 수정, 선택 및 후속 제안을 모두 구현하도록 승인한 범위다. 아래 항목은 모두 구현했으며 대응 자동·모의 검증을 제공한다. 최종 실행 결과와 배포 파일은 PR의 검증 내역 및 패키지의 packaged-ui-report.json에서 확인한다. 병합은 하지 않는다.

상태는 구현 완료 여부를 나타낸다. 관련 검증 파일과 실행 결과를 함께 확인한다. `검증`은 해당 자동·모의 검증 범위에서 확인했다는 뜻이며 실제 API 품질이나 모든 Windows 환경을 보증하지 않는다.

| ID | 작업 | 상태 | 구현·검증 근거 |
| --- | --- | --- | --- |
| IMG-01 | 배포 진입점의 화면 주사위 복원 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-02 | 랜덤 후 상황 전환 유지, 명시적 그림 고정 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-03 | 추가 세트 ZIP 가져오기와 미리보기·결과·즉시 선택 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-04 | ZIP 번호 자동 배정, 중복 재사용, 충돌·누락·손상·경로 검사와 롤백 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-05 | 가져온 세트를 사용자 프로필에 보관, 기존 설치 폴더 세트 보존·이전 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-06 | 설정·주사위·ZIP·대화의 공통 목록·적용 경로 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-07 | 작동하지 않는 상황별 내장 세트 선택 제거 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-08 | 갤러리 휠이 현재 창에서만 동작 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-09 | 손상 이미지 제외, 로딩·저장 성공 후 적용, 실패 복구 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-10 | 전체 세트·상황별 상세 설정·실제 이미지 출처 표시 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-11 | 반응형 갤러리, 선택 표시·필터·순차 썸네일 로딩 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-12 | 자연어 이미지 변경 제안, 범위 확인, 전후 미리보기, 적용·취소·되돌리기 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-13 | 오프라인 이미지 선택기와 명시적 /이미지 단축 명령 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| IMG-14 | 오래된 제안 재검증·중복 적용 방지·이미지 변경만 되돌리기 | 구현 | `desktop_gallery.py`, `image_catalog.py`, `image_actions.py`, `asset_pack_import.py`; `test_random_gallery`, `test_asset_pack_import`, `test_image_actions`, `test_image_catalog` |
| UI-01 | 말풍선=대화, 시계·캐릭터=설정, 드래그 이동 유지 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-02 | 중복 대화 버튼 정리, 트레이·단축키 접근 유지 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-03 | 설정·기록 화면 왕복과 저장·배율 변경 후 현재 상황 그림 유지 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-04 | 설정 탭과 하단 고정 저장·미저장 표시·버리기 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-05 | 미저장 초안 유지, 외부 이미지 변경 시 다른 초안 보존 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-06 | 첫 실행 조작·숨기기 안내, AI 없이 시작·연결 안내 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-07 | 상태별 트레이 자리비움/복귀 이름 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-08 | Tab/Shift+Tab, 출처 Enter, 포커스 표시·스크롤 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-09 | 모든 보조창 화면 내 배치·재열기·항상 위 일관성 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-10 | 대화 글자 확대·복사, 긴 입력 글자 수 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| UI-11 | 날씨창 일회성 도시 조회·기본 지역 별도 저장 | 구현 | `desktop_compact.py`, `assistant_ai/ui*.py`; `test_desktop_workflows`, `test_assistant_ui_interactions`, `test_assistant_settings_memory_ui`, `package_smoke.py` |
| AI-01 | 취소 즉시 새 전송, 늦은 결과 격리, 동작 중복 실행 방지 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-02 | 실패한 메시지 재시도·수정, 새 초안 보존 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-03 | 창 숨기기와 응답 취소 분리 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-04 | 이벤트 기본 대사 즉시 표시·유효한 AI만 후속 표시 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-05 | 최근 이벤트 대사 맥락·반복 억제 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-06 | 이벤트 종류별 허용·오늘만 조용히 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-07 | 현재 시각·시간대·말투·타이머 이벤트 맥락 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-08 | 과거 날씨와 현재 날씨 구분 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-09 | 날씨+타이머 복합 요청의 후속 동작 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-10 | 미국 지역 약어를 국가 코드로 오해하지 않기 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-11 | 웹 검색 허용 토글·검색 상태·출처 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-12 | 키 없이 오늘 상태 조회, 기존 타이머 계산 재사용 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-13 | 현재 모델·확정 사용량·미확인 예약·잔여 한도·집계 설명 | 구현 | `assistant_ai/service.py`, `api.py`, `desktop.py`, `weather.py`, `timer_tools.py`; 각 대응 테스트 및 `test_assistant_desktop_flow` |
| AI-14 | 후속 요청: 공개 API 모델 9종 선택·설명·단가, 기존 선택·직접 입력 유지 | 구현 | `assistant_ai/config.py`, `api.py`, `ui_settings.py`; `test_assistant_models`, `package_smoke.py`. 계정별 권한·크레딧·실제 API 응답은 별도 확인 |
| KEY-01 | 이번 실행에만 키 보관 / Windows DPAPI 저장 선택 | 구현 | `assistant_ai/config.py`, `service.py`, `ui_settings.py`; `test_assistant_config_extended`, `test_assistant_service`, `test_assistant_api` |
| KEY-02 | 기존 키 유지·삭제·저장 모드 변경 실패 시 보존 | 구현 | `assistant_ai/config.py`, `service.py`, `ui_settings.py`; `test_assistant_config_extended`, `test_assistant_service`, `test_assistant_api` |
| KEY-03 | 사용자 실행 연결 시험, 오류·사용 준비 상태 | 구현 | `assistant_ai/config.py`, `service.py`, `ui_settings.py`; `test_assistant_config_extended`, `test_assistant_service`, `test_assistant_api` |
| MEM-01 | 대화 저장과 장기 기억 사용 분리·기존 데이터 호환 | 구현 | `assistant_ai/memory.py`, `service.py`, `ui_memory.py`; `test_assistant_memory`, `test_assistant_service`, `test_assistant_settings_memory_ui` |
| MEM-02 | 저장 OFF/ON 전환 후 현재 대화 보존, 이전 임시 대화 무단 저장 금지 | 구현 | `assistant_ai/memory.py`, `service.py`, `ui_memory.py`; `test_assistant_memory`, `test_assistant_service`, `test_assistant_settings_memory_ui` |
| MEM-03 | 기억 수정·고정 선호·공통 글자 제한·중복 안내 | 구현 | `assistant_ai/memory.py`, `service.py`, `ui_memory.py`; `test_assistant_memory`, `test_assistant_service`, `test_assistant_settings_memory_ui` |
| MEM-04 | 삭제 범위·건수·저장 결과 표시 | 구현 | `assistant_ai/memory.py`, `service.py`, `ui_memory.py`; `test_assistant_memory`, `test_assistant_service`, `test_assistant_settings_memory_ui` |
| DATA-01 | 선택형 사용자 데이터 백업·복원, 이미지 ZIP과 구분 | 구현 | `user_data_backup.py`, `backup_ui.py`; `test_user_data_backup`, `test_backup_ui`, `docs/BACKUP_RESTORE.md` |
| DATA-02 | 복원 전 현재 데이터 백업·검증·일괄 적용·실패 롤백 | 구현 | `user_data_backup.py`, `backup_ui.py`; `test_user_data_backup`, `test_backup_ui`, `docs/BACKUP_RESTORE.md` |
| DATA-03 | SQLite 일관된 백업, 진행 중 요청과 복원 충돌 방지 | 구현 | `user_data_backup.py`, `backup_ui.py`; `test_user_data_backup`, `test_backup_ui`, `docs/BACKUP_RESTORE.md` |
| DATA-04 | API 키 제외, 기본 진단에서 개인 내용·경로 제외 | 구현 | `user_data_backup.py`, `backup_ui.py`; `test_user_data_backup`, `test_backup_ui`, `docs/BACKUP_RESTORE.md` |
| DATA-05 | 기존 별도 AI 리뷰 데이터 자동 합치지 않기 | 구현 | `user_data_backup.py`, `backup_ui.py`; `test_user_data_backup`, `test_backup_ui`, `docs/BACKUP_RESTORE.md` |
| REL-01 | 소스 자동 시작을 배포 진입점과 통일 | 구현 | `settings.py`, `.github/workflows/tests.yml`, `.github/workflows/desktop-package.yml`, `package_smoke.py`, 사용 안내와 실기 목록 |
| REL-02 | 기존 타이머·기록·알림 회귀, 소스 컴파일·전체 테스트 | 구현 | `settings.py`, `.github/workflows/tests.yml`, `.github/workflows/desktop-package.yml`, `package_smoke.py`, 사용 안내와 실기 목록 |
| REL-03 | Windows DPAPI·실행·DPI·클릭 검사 및 EXE 패키지 | 구현 · Windows CI 결과 별도 | `settings.py`, `.github/workflows/tests.yml`, `.github/workflows/desktop-package.yml`, `package_smoke.py`, 사용 안내와 실기 목록 |
| REL-04 | 버전·설치·사용 안내·수동 실기 목록·배포 파일 | 구현 | `settings.py`, `.github/workflows/tests.yml`, `.github/workflows/desktop-package.yml`, `package_smoke.py`, 사용 안내와 실기 목록 |

## 실제 환경 검증

- 실제 OpenAI API 호출·과금 시험은 자동화에서 하지 않는다. 가짜 응답·지연·오류로 동작을 검증하고, 실기에서 사용자가 연결 시험과 응답 품질을 확인한다.
- 사용자의 실제 이미지 ZIP은 제공된 파일을 확보한 경우에만 별도로 검증한다. 자동 테스트의 합성 ZIP과 구분한다.
- Windows CI의 DPI·시작 검사는 실행 결과를 기록한다. 물리 모니터 분리, 한국어 IME, Narrator/NVDA, 장시간 실사용은 별도 실기 항목이다.

## 보완한 경계 조건

- 2.1.3 이미지: 상황별 행을 실제 상위 프레임 안에 만들고, 큰 조상 프레임의 포커스 이벤트로 설정 화면이 잘못 스크롤되지 않게 한다. 미리보기와 적용을 분리하며 다른 역할의 그림도 선택한 상황에 지정한다. 화면 좌표에서 실제 버튼이 클릭 대상으로 잡히는지, 적용 파일과 화면 픽셀·저장·재시작이 일치하는지 검사한다. 자리비움 중 평상시 이미지를 바꿔도 타이머 상황은 유지한다. 좁은 이미지 승인창은 각 열에 필요한 실제 버튼 너비로 배치해 불필요하게 세 줄로 쌓이지 않게 한다. Windows에서 관찰한 버튼 크기로 잘림을 재현하고 창과 하단 영역 양쪽 경계를 검사한다.
- 2.1.3 대사: 긴 원문을 기존 말풍선의 최대 3줄 Text 영역에서 휠·스크롤바·키보드로 읽는다. 별도 전문 창을 여는 메인 경로를 제거하고 명시적인 대화 버튼을 둔다. Windows 네이티브 입력 대기열 원칙을 유지하며 Text·스크롤바·버튼에는 실제 입력이 도달하도록 한다. `test_assistant_widget_readability`, `test_assistant_windows_hitbox`, `test_assistant_ui_interactions`, `package_smoke`에서 검사한다.
- 2.1.3 AI: 새 설정의 정기 간격은 1분, 범위는 1~120분이며 이전 저장값을 보존한다. 대화창의 단순 표시와 실제 작성·읽기·대기 상태를 구분한다. AI 전용 재잘대기는 독립 스위치와 공통 간격·요청 스케줄을 사용한다. 두 모드를 함께 켜도 중복 호출하지 않으며 기존 한도, 오늘 쉬기, 요청 취소와 늦은 응답 차단을 따른다. 상태 조회는 API 호출을 만들지 않고 오류 원문·키를 노출하지 않는다. 가짜 시계·API·지연 응답으로 간격, 설정 전환, 차단 이유와 데이터 보존을 검증한다.
- 2.1.2 실기 반영: 전체 세트 이미지 미리보기 탐색은 실제 선택·저장값을 보존한다. 승인창은 하단 작업 버튼을 먼저 배치하고 긴 본문을 스크롤한다. 자리비움의 현재 구간 시계는 집중 시간과 분리하고 일별 기록 누적은 유지한다. 평소 대사 반복을 줄이고 대화창 닫기와 답변 지우기를 분리한다. 선택형 상황·정기 AI 대화는 간격, 최근 대화와 사용 중 보호, 오늘 조용히와 기존 한도를 따른다. `test_random_gallery`, `test_assistant_ui_interactions`, `test_timer_engine`, `test_desktop_workflows`, `test_messages`, `test_assistant_desktop_flow` 및 패키지 UI 검사로 검증한다.
- 2.1.1: 네이티브 말풍선 콜백에서 Tk를 다시 호출하던 치명적 종료 경로를 제거했다. 콜백은 Python 대기열에 클릭을 저장하고 Tk의 정기 콜백이 처리한다. 오래된 클릭·종료 후 클릭은 버린다. EXE 검사에 PostMessageW를 거친 전체보기, 닫기·재열기·연속 클릭, 기존 대화·기억·초안 보존과 네 가지 배율을 추가했다. 별도로 파괴된 전체보기 창의 재생성과 창을 여는 중 종료되는 경우도 검사한다.
- 손상된 AI 설정 파일을 읽어도 기존 Windows 보호 키를 삭제하지 않는다. 설정 복원도 대상 PC의 키 보관 정책을 유지한다. 두 번 재시작하는 회귀 검증을 포함한다.
- 대화 완료·실패·취소·재시작 중단 상태를 본문과 분리해 저장하며, 늦은 응답이 종료된 기록을 덮지 못하게 한다.
- 지연된 갤러리 리사이즈는 키보드 포커스와 스크롤을 보존한다.
- 미완료 복원 저널이 있으면 정상 타이머 시작을 막아 혼합 상태에 추가 기록을 저장하지 않는다. 강제 종료·전원 장애 후의 수동 복구 절차는 백업 안내에 명시한다.
- 취소는 앱의 기다림과 후속 적용을 중단한다. 서버에 이미 전달한 요청의 실행·청구를 철회한다고 보장하지 않는다. 실제 연결이 종료되기 전에는 데이터 복원을 시작하지 않는다.
- 실제 API 응답 품질·계정 인증·과금, 사용자의 실제 ZIP, 물리 모니터·한국어 IME·화면 읽기·절전은 자동 테스트 결과와 별도로 확인한다.
