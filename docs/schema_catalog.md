# 논리설계 — 관계 스키마 (DB 카탈로그에서 자동 생성)

표기: **굵게** = 기본키(PK), *기울임* = 외래키(FK), ***굵은 기울임*** = PK이면서 FK, `UQ` = 유니크, `?` = NULL 허용.

## 관계 스키마

- **protection_state**(**state_code**, label_ko `UQ`, allows_login, allows_transfer, closes_case, sort_order `UQ`)
- **allowed_transition**(***from_state***, ***to_state***, revoke_sessions, rotate_credential, snapshot_assets, description)
- **operator**(**operator_id**, username `UQ`, display_name, is_active, created_at)
- **account**(***account_id***, login_id `UQ`, nickname `UQ`, email, password_hash?, *credential_version*, *state_code*, created_at)
- **credential_history**(***account_id***, **version**, reason, changed_at, *operator_id*?)
- **device**(**device_id**, fingerprint `UQ`, platform, first_seen_at)
- **account_device**(***account_id***, ***device_id***, first_seen_at, last_seen_at, trusted_at?, is_trusted)
- **game_session**(**session_id**, token_hash `UQ`, *account_id*, *device_id*, ip_address, *issued_credential_version*, issued_at, expires_at, revoked_at?, *revoked_case_id*?, *revoked_seq*?, revoke_reason?)
- **login_attempt**(**attempt_id**, *account_id*, *device_id*, ip_address, attempted_at, failure_reason?, *session_id* `UQ`?, success)
- **risk_rule**(**rule_code**, name_ko, window_minutes?, threshold?, severity, is_enabled)
- **risk_signal**(**signal_id**, *rule_code*, *trigger_attempt_id*, detected_at, *case_id*?)
- **burst_signal**(***signal_id***, *rule_code*, failures_in_window, window_minutes)
- **protection_case**(**case_id**, *account_id*, opened_at, closed_at?)
- **case_transition**(***case_id***, **seq**, *from_state*, *to_state*, *operator_id*?, reason, transitioned_at)
- **case_asset_snapshot**(***case_id***, ***item_id***, captured_at)
- **item_template**(**template_id**, name `UQ`, rarity, is_tradable)
- **item**(**item_id**, *template_id*, *owner_account_id*, acquired_at)
- **item_transfer**(**transfer_id**, *item_id*, *to_account_id*, *session_id*, requested_at, decided_at, reject_reason?, result)

## 외래키

| 테이블 | 컬럼 | → 참조 테이블(컬럼) | 비고 |
|---|---|---|---|
| allowed_transition | from_state | protection_state(state_code) |  |
| allowed_transition | to_state | protection_state(state_code) |  |
| account | account_id, credential_version | credential_history(account_id, version) | 커밋 시점 검사 (DEFERRABLE) |
| account | state_code | protection_state(state_code) |  |
| credential_history | account_id | account(account_id) |  |
| credential_history | operator_id | operator(operator_id) |  |
| account_device | account_id | account(account_id) |  |
| account_device | device_id | device(device_id) |  |
| game_session | account_id, device_id | account_device(account_id, device_id) |  |
| game_session | account_id, issued_credential_version | credential_history(account_id, version) |  |
| game_session | revoked_case_id, revoked_seq | case_transition(case_id, seq) |  |
| login_attempt | account_id | account(account_id) |  |
| login_attempt | device_id | device(device_id) |  |
| login_attempt | session_id | game_session(session_id) |  |
| risk_signal | trigger_attempt_id | login_attempt(attempt_id) |  |
| risk_signal | case_id | protection_case(case_id) |  |
| risk_signal | rule_code | risk_rule(rule_code) |  |
| burst_signal | signal_id, rule_code | risk_signal(signal_id, rule_code) |  |
| protection_case | account_id | account(account_id) |  |
| case_transition | from_state, to_state | allowed_transition(from_state, to_state) |  |
| case_transition | case_id | protection_case(case_id) |  |
| case_transition | operator_id | operator(operator_id) |  |
| case_asset_snapshot | case_id | protection_case(case_id) |  |
| case_asset_snapshot | item_id | item(item_id) |  |
| item | owner_account_id | account(account_id) |  |
| item | template_id | item_template(template_id) |  |
| item_transfer | item_id | item(item_id) |  |
| item_transfer | session_id | game_session(session_id) |  |
| item_transfer | to_account_id | account(account_id) |  |

## 복합 유니크 · 부분 유니크

- risk_signal: UNIQUE(signal_id, rule_code)
- risk_signal: UNIQUE(rule_code, trigger_attempt_id)
- protection_case: `btree (account_id) WHERE (closed_at IS NULL)` (uk_protection_case_one_open)

## CHECK 제약

- allowed_transition.ck_allowed_transition_distinct: `CHECK (((from_state)::text <> (to_state)::text))`
- account.ck_account_credential_version: `CHECK ((credential_version >= 1))`
- account.ck_account_password_required: `CHECK (((password_hash IS NOT NULL) OR ((state_code)::text = ANY ((ARRAY['PROTECTED'::character varying, 'RECOVERING'::character varying, 'LOCKED'::character varying])::text[]))))`
- credential_history.ck_credential_history_reason: `CHECK (((reason)::text = ANY ((ARRAY['INITIAL'::character varying, 'USER_CHANGE'::character varying, 'FORCED_ROTATION'::character varying, 'RECOVERY_RESET'::character varying])::text[])))`
- credential_history.ck_credential_history_version: `CHECK ((version >= 1))`
- device.ck_device_fingerprint_hex: `CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text))`
- device.ck_device_platform: `CHECK (((platform)::text = ANY ((ARRAY['WINDOWS'::character varying, 'MAC'::character varying, 'ANDROID'::character varying, 'IOS'::character varying, 'OTHER'::character varying])::text[])))`
- account_device.ck_account_device_seen_order: `CHECK ((last_seen_at >= first_seen_at))`
- game_session.ck_game_session_expiry: `CHECK ((expires_at > issued_at))`
- game_session.ck_game_session_revoked_by: `CHECK (((revoked_case_id IS NULL) OR (revoked_at IS NOT NULL)))`
- game_session.ck_game_session_revoked_pair: `CHECK (((revoked_case_id IS NULL) = (revoked_seq IS NULL)))`
- game_session.ck_game_session_revoked_time: `CHECK (((revoked_at IS NULL) OR (revoked_at >= issued_at)))`
- game_session.ck_game_session_token_hex: `CHECK ((token_hash ~ '^[0-9a-f]{64}$'::text))`
- login_attempt.ck_login_attempt_failure_reason: `CHECK (((failure_reason)::text = ANY ((ARRAY['BAD_PASSWORD'::character varying, 'STATE_BLOCKED'::character varying, 'PASSWORD_RESET_REQUIRED'::character varying])::text[])))`
- login_attempt.ck_login_attempt_session_success: `CHECK (((failure_reason IS NULL) = (session_id IS NOT NULL)))`
- risk_rule.ck_risk_rule_burst_params: `CHECK ((((rule_code)::text <> 'FAILED_BURST'::text) OR ((window_minutes IS NOT NULL) AND (threshold IS NOT NULL))))`
- risk_rule.ck_risk_rule_severity: `CHECK (((severity >= 1) AND (severity <= 3)))`
- risk_rule.ck_risk_rule_threshold: `CHECK ((threshold > 0))`
- risk_rule.ck_risk_rule_window: `CHECK ((window_minutes > 0))`
- burst_signal.ck_burst_signal_failures: `CHECK ((failures_in_window > 0))`
- burst_signal.ck_burst_signal_window: `CHECK ((window_minutes > 0))`
- protection_case.ck_protection_case_period: `CHECK (((closed_at IS NULL) OR (closed_at >= opened_at)))`
- case_transition.ck_case_transition_reason: `CHECK ((length(btrim((reason)::text)) > 0))`
- case_transition.ck_case_transition_seq: `CHECK ((seq >= 1))`
- item_template.ck_item_template_rarity: `CHECK (((rarity)::text = ANY ((ARRAY['COMMON'::character varying, 'RARE'::character varying, 'EPIC'::character varying, 'LEGENDARY'::character varying])::text[])))`
- item_transfer.ck_item_transfer_decided_time: `CHECK ((decided_at >= requested_at))`
- item_transfer.ck_item_transfer_reject_reason: `CHECK (((reject_reason)::text = ANY ((ARRAY['SESSION_REVOKED'::character varying, 'SESSION_EXPIRED'::character varying, 'CREDENTIAL_ROTATED'::character varying, 'STATE_BLOCKED'::character varying, 'NOT_OWNER'::character varying, 'NOT_TRADABLE'::character varying])::text[])))`

## 보조 인덱스

- account_device: `btree (device_id)`
- game_session: `btree (account_id, issued_at)`
- game_session: `btree (account_id) WHERE (revoked_at IS NULL)`
- item: `btree (owner_account_id)`
- item_transfer: `btree (item_id, decided_at)`
- item_transfer: `btree (session_id)`
- login_attempt: `btree (account_id, attempted_at)`
- protection_case: `btree (account_id, opened_at)`
- risk_signal: `btree (case_id)`
- risk_signal: `btree (trigger_attempt_id) WHERE (case_id IS NULL)`

## 트리거

- account.trg_account_state_guard
- account.trg_account_state_recorded (지연 제약 트리거)
