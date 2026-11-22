-- =====================================================================
-- 04_grants.sql — 최소 권한
-- 실행 역할: ap_owner
--
--   ap_owner : 스키마·테이블·함수 소유자 (마이그레이션 전용, 앱은 사용하지 않음)
--   ap_ops   : 운영 화면(Django). 조회 + 상태 전이·복구·탐지 함수만
--   ap_game  : 게임 서버 역할(데모에서는 공격 스크립트). 로그인·아이템 이동 함수만
-- 두 앱 역할 모두 ap 스키마 테이블에 INSERT/UPDATE/DELETE 권한이 전혀 없다.
-- =====================================================================
SET search_path = ap, ext;

REVOKE ALL ON SCHEMA ap, ext FROM PUBLIC;
GRANT USAGE ON SCHEMA ap TO ap_ops, ap_game;

-- 함수는 기본적으로 PUBLIC 에 실행 권한이 있으므로 먼저 회수 (SECURITY DEFINER 함수는 특히 중요)
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA ap FROM PUBLIC;

-- 운영 역할: 조회
GRANT SELECT ON protection_state, allowed_transition, risk_rule, operator, item_template,
                protection_case, case_transition, case_asset_snapshot, item, item_transfer,
                device, account_device, login_attempt, risk_signal, burst_signal, credential_history
             TO ap_ops;
GRANT SELECT (account_id, login_id, nickname, state_code, credential_version, created_at)
             ON account TO ap_ops;                         -- email, password_hash 제외
GRANT SELECT (session_id, account_id, device_id, ip_address, issued_credential_version, issued_at,
              expires_at, revoked_at, revoke_reason, revoked_case_id, revoked_seq)
             ON game_session TO ap_ops;                    -- token_hash 제외
GRANT SELECT ON v_session_status, v_account_overview, v_risk_queue, v_audit_timeline TO ap_ops;

-- 운영 역할: 정책 함수
GRANT EXECUTE ON FUNCTION transition_account(bigint, text, integer, text),
                          reset_password(bigint, text, integer),
                          detect_risks(bigint, timestamptz)
             TO ap_ops;

-- 게임 서버 역할: 로그인·아이템 이동 함수만 (조회 권한도 없음)
GRANT EXECUTE ON FUNCTION login(text, text, text, text, inet),
                          transfer_item(text, bigint, bigint)
             TO ap_game;
