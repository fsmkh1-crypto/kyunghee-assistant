# 승아 타이머 2.1.7: GPT-6.2 전용 모델 선택

- AI 모델 목록은 `gpt-6.2-sol`(기본), `gpt-6.2-astra` 두 가지입니다. 직접 입력 대신 목록에서 선택합니다.
- 기존 모델 선택은 Sol로 전환합니다. API 키, 사용량 기록, 대화, 이미지, 타이머 데이터, 사용 동의와 비용 한도는 초기화하지 않습니다. 설정을 읽기만 할 때 파일을 덮어쓰지 않으며 다음 저장 시 새 선택을 저장합니다.
- 두 모델 모두 Responses API와 `low` 추론을 사용합니다. Standard 요금 기준 추정 비용을 갱신했습니다. 이전 모델의 가격표는 과거 기록 처리용으로만 보존합니다.
- Sol은 100만 토큰당 입력 $2, 캐시 입력 $0.10, 출력 $10입니다. Astra는 입력 $8, 캐시 입력 $0.40, 출력 $40입니다. 이전 저가 모델에서 이전하면 비용이 높아질 수 있습니다. 기존 하루 비용 한도는 그대로 적용됩니다.
- 2.1.6-hotfix.1의 자정 통계, 복원, 상태 복구, 알림 수정도 포함합니다.
- 기존 앱을 종료하고 새 ZIP을 별도 폴더에 풀어 EXE와 `_internal`을 함께 사용합니다. 실행 중인 기존 앱을 자동 교체하지 않습니다.

## 검증 출처

2026-11-18 확인: https://developers.openai.com/api/docs/models/gpt-6.2-sol.md , https://developers.openai.com/api/docs/models/gpt-6.2-astra , https://developers.openai.com/api/docs/guides/latest-model . 실제 API 권한과 결제 상태는 사용자의 계정에 따라 다르며 실 API 유료 호출은 검증하지 않았습니다.
