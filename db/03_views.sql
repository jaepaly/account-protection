-- =====================================================================
-- 03_views.sql — 운영 화면용 뷰
-- 실행 역할: ap_owner
-- 뷰는 소유자(ap_owner) 권한으로 실행되므로, 운영 역할(ap_ops)은 원본 테이블의
-- 민감 컬럼(email, password_hash, token_hash)에 권한이 없어도 마스킹된 결과는 볼 수 있다.
-- =====================================================================
SET search_path = ap, ext;

-- 세션 상태 (계산 컬럼)
CREATE OR REPLACE VIEW v_session_status AS
SELECT gs.session_id, gs.account_id, gs.device_id, gs.ip_address,
       gs.issued_at, gs.expires_at, gs.revoked_at, gs.revoke_reason,
       CASE WHEN gs.revoked_at IS NOT NULL                              THEN 'REVOKED'
            WHEN gs.expires_at <= now()                                 THEN 'EXPIRED'
            WHEN gs.issued_credential_version <> a.credential_version   THEN 'STALE_CREDENTIAL'
            ELSE 'ACTIVE' END AS status
  FROM game_session gs
  JOIN account a ON a.account_id = gs.account_id;

-- 계정 개요 (이메일 마스킹) — 운영 화면 목록·상세
CREATE OR REPLACE VIEW v_account_overview AS
SELECT a.account_id, a.login_id, a.nickname,
       regexp_replace(a.email, '^(.)[^@]*(@.*)$', '\1***\2') AS email_masked,
       a.state_code, ps.label_ko AS state_label, a.credential_version, a.created_at,
       (SELECT count(*) FROM game_session gs
         WHERE gs.account_id = a.account_id AND gs.revoked_at IS NULL
           AND gs.expires_at > now() AND gs.issued_credential_version = a.credential_version) AS active_sessions,
       (SELECT count(*) FROM risk_signal rs JOIN login_attempt la ON la.attempt_id = rs.trigger_attempt_id
         WHERE la.account_id = a.account_id AND rs.case_id IS NULL)                         AS open_signals,
       (SELECT count(*) FROM item i WHERE i.owner_account_id = a.account_id)                AS item_count,
       pc.case_id AS open_case_id
  FROM account a
  JOIN protection_state ps ON ps.state_code = a.state_code
  LEFT JOIN protection_case pc ON pc.account_id = a.account_id AND pc.closed_at IS NULL;

-- 위험 신호 큐 — 운영 화면 첫 페이지
CREATE OR REPLACE VIEW v_risk_queue AS
SELECT rs.signal_id, la.account_id, a.login_id, a.state_code,
       rs.rule_code, rr.name_ko AS rule_name, rr.severity,
       la.attempted_at AS occurred_at, rs.detected_at,
       la.ip_address, la.device_id, bs.failures_in_window, bs.window_minutes, rs.case_id
  FROM risk_signal rs
  JOIN login_attempt la ON la.attempt_id = rs.trigger_attempt_id
  JOIN account a        ON a.account_id = la.account_id
  JOIN risk_rule rr     ON rr.rule_code = rs.rule_code
  LEFT JOIN burst_signal bs ON bs.signal_id = rs.signal_id;

-- 감사 타임라인 — 계정별 사건을 한 줄로 합친다 (account_id 로 걸러 쓰는 것을 전제)
CREATE OR REPLACE VIEW v_audit_timeline AS
SELECT la.account_id, la.attempted_at AS occurred_at,
       CASE WHEN la.success THEN 'LOGIN_SUCCESS' ELSE 'LOGIN_FAILED' END AS event_type,
       concat_ws(' ', 'device#' || la.device_id, 'ip ' || host(la.ip_address), la.failure_reason) AS detail,
       NULL::bigint AS case_id, la.attempt_id AS ref_id
  FROM login_attempt la
UNION ALL
SELECT la.account_id, la.attempted_at, 'RISK_SIGNAL',
       concat_ws(' ', rs.rule_code,
                 CASE WHEN bs.signal_id IS NOT NULL
                      THEN bs.failures_in_window || ' failures / ' || bs.window_minutes || ' min'
                      ELSE 'device#' || la.device_id END),
       rs.case_id, rs.signal_id
  FROM risk_signal rs
  JOIN login_attempt la ON la.attempt_id = rs.trigger_attempt_id
  LEFT JOIN burst_signal bs ON bs.signal_id = rs.signal_id
UNION ALL
SELECT pc.account_id, ct.transitioned_at, 'STATE_TRANSITION',
       ct.from_state || ' -> ' || ct.to_state || ' by ' || coalesce(o.display_name, 'SYSTEM') || ': ' || ct.reason,
       ct.case_id, ct.seq
  FROM case_transition ct
  JOIN protection_case pc ON pc.case_id = ct.case_id
  LEFT JOIN operator o    ON o.operator_id = ct.operator_id
UNION ALL
SELECT gs.account_id, gs.revoked_at, 'SESSION_REVOKED',
       'session#' || gs.session_id || ' ' || gs.revoke_reason, gs.revoked_case_id, gs.session_id
  FROM game_session gs
 WHERE gs.revoked_at IS NOT NULL
UNION ALL
SELECT gs.account_id, it.decided_at, 'TRANSFER_' || it.result,
       'item#' || it.item_id || ' -> account#' || it.to_account_id || coalesce(' (' || it.reject_reason || ')', ''),
       NULL, it.transfer_id
  FROM item_transfer it
  JOIN game_session gs ON gs.session_id = it.session_id;
