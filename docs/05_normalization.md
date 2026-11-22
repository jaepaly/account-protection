## 정규화 근거

**3NF 분해 — 아이템 종류 분리.** 아이템의 이름·등급·거래 가능 여부는 개별 아이템(item_id)이 아니라 종류(template_id)에 따라 결정된다(item_id → template_id → rarity, 이행 종속). 한 테이블에 두면 같은 종류의 아이템 수천 개에 같은 값이 반복되고, 「이 종류를 거래 불가로 변경」이 수천 행 갱신이 된다. 그래서 item_template으로 분리했다.

**파생 가능한 값은 저장하지 않는다.**


| 뺀 속성 | 유도하는 곳 | 저장했다면 생길 문제 |
|---|---|---|
| risk_signal.account_id, occurred_at | trigger_attempt_id → login_attempt | 신호와 원인 로그인의 계정이 어긋날 수 있음 |
| item_transfer.from_account_id | session_id → game_session.account_id | 요청 세션과 보낸 계정이 어긋날 수 있음 |
| protection_state.is_terminal | allowed_transition에 나가는 전이가 없는 상태 | 정책을 바꿀 때 두 곳을 함께 고쳐야 함 |
| protection_case.close_state | 마지막 case_transition.to_state | 전이 기록과 케이스 결과가 어긋날 수 있음 |

**의도적으로 남긴 중복과 이유.**

- **account.state_code** — 현재 상태는 마지막 전이 기록에서 유도할 수 있지만, 모든 로그인과 아이템 이동이 이 값을 검사하고 잠근다. 매번 전이 이력을 뒤지면 느리고, 잠금 대상도 모호해진다. 그래서 계정 행에 두고, 「상태가 바뀌면 커밋 시점에 그 전이가 기록돼 있어야 한다」를 지연 제약 트리거로 강제해 둘이 어긋나지 않게 했다.
- **protection_case.opened_at / closed_at** — 첫 전이·마지막 전이 시각과 겹친다. 그래도 「계정당 열린 케이스 1개」를 부분 유니크 인덱스(`WHERE closed_at IS NULL`)로 걸려면 이 컬럼이 테이블에 실제로 있어야 한다.

**BCNF 점검.** 모든 테이블에서 비자명 함수 종속의 왼쪽은 슈퍼키다. 후보키가 여러 개인 테이블도 각 후보키가 나머지 속성을 결정하므로 BCNF를 만족한다. 예: account의 {account_id}, {login_id}, {nickname} / game_session의 {session_id}, {token_hash} / login_attempt의 {attempt_id}, {session_id}(NULL 제외).

**약한 엔티티와 연관 엔티티.** credential_history(계정+버전)와 case_transition(케이스+순번)은 소유 엔티티의 키를 포함한 복합 기본키를 갖는 약한 엔티티다. account_device와 case_asset_snapshot은 M:N 관계를 표현하는 연관 엔티티이며, 관계 자체의 속성(신뢰 여부, 동결 시각)을 갖는다.
