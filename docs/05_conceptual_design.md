# Conceptual Design — 계정 보호 상태기계 ER 다이어그램

<!--ERD-->

**구성 (엔티티 17개, 4개 영역)**

- **신원·인증** — account, credential_history(약한 엔티티: 계정+버전), device, account_device(계정–기기 M:N, 신뢰 여부), game_session, login_attempt
- **보호 정책** — protection_state, allowed_transition(상태의 자기참조 M:N + 전이별 동반 조치), protection_case, case_transition(약한 엔티티: 케이스+순번), operator, case_asset_snapshot(케이스–아이템 M:N)
- **탐지** — risk_rule(임계치를 데이터로), risk_signal(원인 로그인 시도 1건에 연결)
- **자산** — item_template, item, item_transfer(거절된 요청도 기록)

**ERD로 표현한 핵심 규칙**

1. 상태 전이는 allowed_transition에 정의된 것만 가능하다. case_transition이 (from, to)를 외래키로 참조하므로 정의되지 않은 전이는 기록 자체가 불가능하다.
2. 「보호」 전이 한 번이 세션 폐기(case_transition → game_session), 자격증명 회전(credential_history 새 버전), 자산 동결(case_asset_snapshot)을 함께 일으킨다. 각 결과에서 원인 전이를 역추적할 수 있다.
3. 세션은 등록된 계정–기기 쌍(account_device)에서만 발급되고, 발급 당시 자격증명 버전을 기억한다. 버전이 바뀌면 폐기 표시가 없어도 무효다.
4. 계정당 진행 중인 보호 케이스는 하나뿐이다(부분 유니크). 케이스가 열릴 때 그 계정의 미처리 위험 신호가 케이스에 연결된다.
5. 위험 신호의 계정·시각, 아이템 이동의 보낸 계정은 각각 원인 로그인과 요청 세션에서 유도되므로 따로 저장하지 않는다.
