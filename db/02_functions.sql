-- =====================================================================
-- 02_functions.sql — 상태기계·로그인·아이템 이동·탐지 (정책 집행 지점)
-- 실행 역할: ap_owner
--
-- 모든 함수는 SECURITY DEFINER(소유자 권한으로 실행)다. 앱 계정은 테이블을 직접
-- 고칠 권한이 없고 이 함수들만 실행할 수 있다(04_grants.sql). 그래서 요청이 어떤
-- 코드 경로로 들어오든 같은 검사를 거친다.
-- SECURITY DEFINER 함수는 search_path를 고정해 다른 스키마 객체 끼워넣기를 막는다.
--
-- 잠금 규약: 모든 함수는 '계정 행'을 가장 먼저 잠근다.
--   상태를 바꾸는 쪽(transition_account, reset_password) → FOR UPDATE (배타)
--   상태를 확인하는 쪽(login, transfer_item)              → FOR SHARE  (공유)
--   → 상태 전이와 로그인/아이템 이동이 같은 계정에서 겹치면 반드시 하나씩 순서대로 처리된다.
-- =====================================================================
SET search_path = ap, ext;

-- ---------------------------------------------------------------------
-- 트리거 1: 허용되지 않은 상태 변경 즉시 거부 (소유자 계정의 직접 UPDATE도 포함)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_account_state_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state_code <> 'NORMAL' THEN
            RAISE EXCEPTION 'NEW_ACCOUNT_MUST_BE_NORMAL: %', NEW.state_code;
        END IF;
    ELSIF NEW.state_code IS DISTINCT FROM OLD.state_code
          AND NOT EXISTS (SELECT 1 FROM ap.allowed_transition t
                          WHERE t.from_state = OLD.state_code AND t.to_state = NEW.state_code) THEN
        RAISE EXCEPTION 'TRANSITION_NOT_ALLOWED: % -> %', OLD.state_code, NEW.state_code
              USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_account_state_guard
    BEFORE INSERT OR UPDATE OF state_code ON account
    FOR EACH ROW EXECUTE FUNCTION trg_account_state_guard();

-- ---------------------------------------------------------------------
-- 트리거 2 (지연 제약 트리거): 상태가 바뀌었으면 커밋 시점에 그 전이가 기록돼 있어야 한다.
--   허용된 전이라도 case_transition 기록 없이 상태만 바꾸면 커밋이 거부된다.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_account_state_recorded() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_state text;
    v_last  text;
BEGIN
    SELECT a.state_code INTO v_state FROM ap.account a WHERE a.account_id = NEW.account_id;
    SELECT ct.to_state INTO v_last
      FROM ap.case_transition ct
      JOIN ap.protection_case pc ON pc.case_id = ct.case_id
     WHERE pc.account_id = NEW.account_id
     ORDER BY ct.transitioned_at DESC, ct.case_id DESC, ct.seq DESC
     LIMIT 1;
    IF v_last IS DISTINCT FROM v_state THEN
        RAISE EXCEPTION 'STATE_CHANGE_NOT_RECORDED: account % is % but last recorded transition is %',
              NEW.account_id, v_state, coalesce(v_last, '(none)');
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_account_state_recorded
    AFTER UPDATE OF state_code ON account
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    WHEN (OLD.state_code IS DISTINCT FROM NEW.state_code)
    EXECUTE FUNCTION trg_account_state_recorded();

-- ---------------------------------------------------------------------
-- 탐지: 로그인 이력에서 규칙을 평가해 위험 신호를 만든다 (중복은 UNIQUE로 무시)
--   p_account_id NULL = 전체 계정, p_since = 이 시각 이후의 시도만 신호 대상
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION detect_risks(p_account_id bigint DEFAULT NULL,
                                        p_since      timestamptz DEFAULT '-infinity')
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ap, ext, pg_temp AS $$
DECLARE
    v_rule  risk_rule%ROWTYPE;
    v_win   interval;
    v_total integer := 0;
    v_cnt   integer;
BEGIN
    -- 규칙 1: 실패 폭주 — window 안의 실패 횟수가 처음으로 threshold 에 '도달한' 시도 하나에 신호
    SELECT * INTO v_rule FROM risk_rule WHERE rule_code = 'FAILED_BURST' AND is_enabled;
    IF FOUND THEN
        v_win := make_interval(mins => v_rule.window_minutes);
        -- 신호(상위)와 실패 폭주 세부(하위)를 한 문장에서 함께 만든다
        WITH cand AS (
        SELECT c.attempt_id, c.fails
          FROM (SELECT w.*,
                       lag(w.fails) OVER (PARTITION BY w.account_id ORDER BY w.attempted_at, w.attempt_id) AS prev_fails
                  FROM (SELECT la.attempt_id, la.account_id, la.attempted_at,
                               count(*) OVER (PARTITION BY la.account_id ORDER BY la.attempted_at
                                              RANGE BETWEEN v_win PRECEDING AND CURRENT ROW) AS fails
                          FROM login_attempt la
                         WHERE NOT la.success
                           AND (p_account_id IS NULL OR la.account_id = p_account_id)
                           AND la.attempted_at >= p_since - v_win) w
               ) c
         WHERE c.fails >= v_rule.threshold
           AND coalesce(c.prev_fails, 0) < v_rule.threshold
           AND c.attempted_at >= p_since
        ), ins AS (
            INSERT INTO risk_signal (rule_code, trigger_attempt_id)
            SELECT 'FAILED_BURST', cand.attempt_id FROM cand
            ON CONFLICT (rule_code, trigger_attempt_id) DO NOTHING
            RETURNING risk_signal.signal_id, risk_signal.trigger_attempt_id
        )
        INSERT INTO burst_signal (signal_id, failures_in_window, window_minutes)
        SELECT ins.signal_id, cand.fails, v_rule.window_minutes
          FROM ins JOIN cand ON cand.attempt_id = ins.trigger_attempt_id;
        GET DIAGNOSTICS v_cnt = ROW_COUNT;
        v_total := v_total + v_cnt;
    END IF;

    -- 규칙 2: 신규 기기 — 신뢰하지 않는 기기에서의 '첫' 로그인 성공
    IF EXISTS (SELECT 1 FROM risk_rule WHERE rule_code = 'NEW_DEVICE' AND is_enabled) THEN
        -- 기기는 원인 시도(login_attempt.device_id)에서 얻으므로 따로 저장하지 않는다
        INSERT INTO risk_signal (rule_code, trigger_attempt_id)
        SELECT 'NEW_DEVICE', f.attempt_id
          FROM (SELECT la.attempt_id, la.account_id, la.device_id, la.attempted_at,
                       row_number() OVER (PARTITION BY la.account_id, la.device_id
                                          ORDER BY la.attempted_at, la.attempt_id) AS nth
                  FROM login_attempt la
                 WHERE la.success
                   AND (p_account_id IS NULL OR la.account_id = p_account_id)) f
          JOIN account_device ad ON ad.account_id = f.account_id AND ad.device_id = f.device_id
         WHERE f.nth = 1
           AND NOT ad.is_trusted
           AND f.attempted_at >= p_since
        ON CONFLICT (rule_code, trigger_attempt_id) DO NOTHING;
        GET DIAGNOSTICS v_cnt = ROW_COUNT;
        v_total := v_total + v_cnt;
    END IF;

    RETURN v_total;
END $$;

-- ---------------------------------------------------------------------
-- 로그인: 시도 기록 + (성공 시) 세션 발급 + 해당 계정 탐지 실행
--   반환 result: OK / BAD_PASSWORD / STATE_BLOCKED / PASSWORD_RESET_REQUIRED / INVALID_CREDENTIALS
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION login(p_login_id   text,
                                 p_password   text,
                                 p_device_key text,
                                 p_platform   text,
                                 p_ip         inet)
RETURNS TABLE (result text, session_token text, login_attempt_id bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ap, ext, pg_temp AS $$
#variable_conflict use_column
DECLARE
    v_acc       account%ROWTYPE;
    v_allows    boolean;
    v_fp        char(64) := encode(digest(p_device_key, 'sha256'), 'hex');
    v_device_id bigint;
    v_fail      text;
    v_token     text;
    v_session   bigint;
    v_attempt   bigint;
BEGIN
    -- 계정 행 공유 잠금: 진행 중인 상태 전이가 있으면 끝날 때까지 기다린다
    SELECT * INTO v_acc FROM account WHERE login_id = p_login_id FOR SHARE;
    IF NOT FOUND THEN
        -- 존재하지 않는 계정: 계정 존재 여부를 드러내지 않도록 같은 형태로 응답
        RETURN QUERY SELECT 'INVALID_CREDENTIALS'::text, NULL::text, NULL::bigint;
        RETURN;
    END IF;

    INSERT INTO device (fingerprint, platform) VALUES (v_fp, p_platform)
        ON CONFLICT (fingerprint) DO NOTHING;
    SELECT d.device_id INTO v_device_id FROM device d WHERE d.fingerprint = v_fp;

    SELECT ps.allows_login INTO v_allows FROM protection_state ps WHERE ps.state_code = v_acc.state_code;
    v_fail := CASE
        WHEN NOT v_allows                                            THEN 'STATE_BLOCKED'
        WHEN v_acc.password_hash IS NULL                             THEN 'PASSWORD_RESET_REQUIRED'
        WHEN crypt(p_password, v_acc.password_hash) <> v_acc.password_hash THEN 'BAD_PASSWORD'
    END;

    IF v_fail IS NULL THEN
        INSERT INTO account_device (account_id, device_id) VALUES (v_acc.account_id, v_device_id)
            ON CONFLICT (account_id, device_id) DO UPDATE          -- 먼저 시작한 트랜잭션이 나중에 도착해도 뒤로 가지 않게
                SET last_seen_at = greatest(account_device.last_seen_at, EXCLUDED.last_seen_at);
        v_token := encode(gen_random_bytes(32), 'hex');   -- 원문은 호출자에게만 돌려주고 해시만 저장
        INSERT INTO game_session (token_hash, account_id, device_id, ip_address,
                                  issued_credential_version, expires_at)
        VALUES (encode(digest(v_token, 'sha256'), 'hex'), v_acc.account_id, v_device_id, p_ip,
                v_acc.credential_version, now() + interval '12 hours')
        RETURNING game_session.session_id INTO v_session;
    END IF;

    INSERT INTO login_attempt (account_id, device_id, ip_address, failure_reason, session_id)
    VALUES (v_acc.account_id, v_device_id, p_ip, v_fail, v_session)
    RETURNING login_attempt.attempt_id INTO v_attempt;

    PERFORM detect_risks(v_acc.account_id, now());

    RETURN QUERY SELECT coalesce(v_fail, 'OK'), v_token, v_attempt;
END $$;

-- ---------------------------------------------------------------------
-- 상태 전이: 허용 전이 확인 → 케이스 열기/찾기 → 전이 기록 → 동반 조치 → 상태 변경
--   모두 한 트랜잭션. 중간에 실패하면 전부 취소된다.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION transition_account(p_account_id  bigint,
                                              p_to_state    text,
                                              p_operator_id integer,
                                              p_reason      text)
RETURNS TABLE (case_id bigint, seq smallint, from_state text, to_state text,
               revoked_sessions integer, snapshot_items integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ap, ext, pg_temp AS $$
#variable_conflict use_column
DECLARE
    v_from    text;
    v_rule    allowed_transition%ROWTYPE;
    v_closes  boolean;
    v_case    bigint;
    v_seq     smallint;
    v_revoked integer := 0;
    v_snap    integer := 0;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'REASON_REQUIRED';
    END IF;

    -- (1) 계정 행 배타 잠금 — 같은 계정의 로그인·아이템 이동·다른 전이와 직렬화
    SELECT a.state_code INTO v_from FROM account a WHERE a.account_id = p_account_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ACCOUNT_NOT_FOUND: %', p_account_id;
    END IF;

    -- (2) 허용 전이 확인
    SELECT * INTO v_rule FROM allowed_transition t
     WHERE t.from_state = v_from AND t.to_state = p_to_state;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'TRANSITION_NOT_ALLOWED: % -> %', v_from, p_to_state;
    END IF;
    SELECT ps.closes_case INTO v_closes FROM protection_state ps WHERE ps.state_code = p_to_state;

    -- (3) 케이스: '정상'에서 벗어날 때 새로 열고, 그 계정의 미처리 위험 신호를 연결
    IF v_from = 'NORMAL' THEN
        INSERT INTO protection_case (account_id) VALUES (p_account_id)
        RETURNING protection_case.case_id INTO v_case;
        UPDATE risk_signal rs SET case_id = v_case
          FROM login_attempt la
         WHERE la.attempt_id = rs.trigger_attempt_id
           AND la.account_id = p_account_id
           AND rs.case_id IS NULL;
    ELSE
        SELECT pc.case_id INTO v_case FROM protection_case pc
         WHERE pc.account_id = p_account_id AND pc.closed_at IS NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'OPEN_CASE_MISSING: account %', p_account_id;
        END IF;
    END IF;

    -- (4) 전이 기록 (계정 잠금 덕분에 순번 계산이 경합하지 않는다)
    SELECT coalesce(max(ct.seq), 0) + 1 INTO v_seq FROM case_transition ct WHERE ct.case_id = v_case;
    INSERT INTO case_transition (case_id, seq, from_state, to_state, operator_id, reason)
    VALUES (v_case, v_seq, v_from, p_to_state, p_operator_id, p_reason);

    -- (5) 동반 조치
    IF v_rule.revoke_sessions THEN
        UPDATE game_session gs
           SET revoked_at = clock_timestamp(),
               revoked_case_id = v_case, revoked_seq = v_seq      -- revoke_reason 은 생성 컬럼
         WHERE gs.account_id = p_account_id AND gs.revoked_at IS NULL AND gs.expires_at > now();
        GET DIAGNOSTICS v_revoked = ROW_COUNT;
    END IF;

    IF v_rule.rotate_credential THEN
        INSERT INTO credential_history (account_id, version, reason, operator_id)
        SELECT a.account_id, a.credential_version + 1, 'FORCED_ROTATION', p_operator_id
          FROM account a WHERE a.account_id = p_account_id;
    END IF;

    IF v_rule.snapshot_assets THEN
        INSERT INTO case_asset_snapshot (case_id, item_id)
        SELECT v_case, i.item_id FROM item i WHERE i.owner_account_id = p_account_id
        ON CONFLICT DO NOTHING;
        GET DIAGNOSTICS v_snap = ROW_COUNT;
    END IF;

    -- (6) 상태 변경 (+ 자격증명 회전). 트리거가 허용 전이를 한 번 더 검사한다.
    UPDATE account a
       SET state_code         = p_to_state,
           credential_version = a.credential_version + CASE WHEN v_rule.rotate_credential THEN 1 ELSE 0 END,
           password_hash      = CASE WHEN v_rule.rotate_credential THEN NULL ELSE a.password_hash END
     WHERE a.account_id = p_account_id;

    -- (7) 정상 복귀·영구 잠금이면 케이스 종료
    IF v_closes THEN
        UPDATE protection_case pc SET closed_at = clock_timestamp() WHERE pc.case_id = v_case;
    END IF;

    RETURN QUERY SELECT v_case, v_seq, v_from, p_to_state, v_revoked, v_snap;
END $$;

-- ---------------------------------------------------------------------
-- 복구용 비밀번호 재설정: '복구 중' 상태에서만, 본인 확인을 마친 운영자가 실행
--   (실서비스라면 본인이 직접 정하지만 MVP에서는 운영자 화면에서 대행)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reset_password(p_account_id   bigint,
                                          p_new_password text,
                                          p_operator_id  integer)
RETURNS integer   -- 새 자격증명 버전
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ap, ext, pg_temp AS $$
DECLARE
    v_state   text;
    v_version integer;
BEGIN
    SELECT a.state_code, a.credential_version INTO v_state, v_version
      FROM account a WHERE a.account_id = p_account_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ACCOUNT_NOT_FOUND: %', p_account_id;
    END IF;
    IF v_state <> 'RECOVERING' THEN
        RAISE EXCEPTION 'RESET_ONLY_IN_RECOVERING: account is %', v_state;
    END IF;
    IF p_new_password IS NULL OR length(p_new_password) < 8 THEN
        RAISE EXCEPTION 'WEAK_PASSWORD: at least 8 characters';
    END IF;

    INSERT INTO credential_history (account_id, version, reason, operator_id)
    VALUES (p_account_id, v_version + 1, 'RECOVERY_RESET', p_operator_id);
    UPDATE account a
       SET credential_version = v_version + 1,
           password_hash      = crypt(p_new_password, gen_salt('bf', 8))
     WHERE a.account_id = p_account_id;
    RETURN v_version + 1;
END $$;

-- ---------------------------------------------------------------------
-- 아이템 이동: 세션 유효성·계정 상태·소유권을 검사하고, 거절도 기록한다
--   입력 오류(없는 아이템·받는 계정, 자기 자신에게 이동)는 예외로 처리하고 기록하지 않는다.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION transfer_item(p_session_token text,
                                         p_item_id       bigint,
                                         p_to_account_id bigint)
RETURNS TABLE (transfer_id bigint, result text, reject_reason text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ap, ext, pg_temp AS $$
#variable_conflict use_column
DECLARE
    v_session_id bigint;
    v_from       bigint;
    v_sess       game_session%ROWTYPE;
    v_acc        account%ROWTYPE;
    v_allows     boolean;
    v_tradable   boolean;
    v_reason     text;
    v_moved      integer;
    v_id         bigint;
BEGIN
    SELECT gs.session_id, gs.account_id INTO v_session_id, v_from
      FROM game_session gs WHERE gs.token_hash = encode(digest(p_session_token, 'sha256'), 'hex');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'INVALID_SESSION';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM account a WHERE a.account_id = p_to_account_id) THEN
        RAISE EXCEPTION 'RECIPIENT_NOT_FOUND: %', p_to_account_id;
    END IF;
    IF p_to_account_id = v_from THEN
        RAISE EXCEPTION 'SAME_ACCOUNT';
    END IF;
    SELECT it.is_tradable INTO v_tradable
      FROM item i JOIN item_template it ON it.template_id = i.template_id
     WHERE i.item_id = p_item_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ITEM_NOT_FOUND: %', p_item_id;
    END IF;

    -- 핵심: 보내는 계정 행에 공유 잠금. 진행 중인 상태 전이(배타 잠금)가 있으면 끝날 때까지 기다리고,
    -- 기다린 뒤에는 바뀐 최신 상태를 읽는다.
    SELECT * INTO v_acc FROM account a WHERE a.account_id = v_from FOR SHARE;
    -- 잠금을 얻은 뒤 세션을 다시 읽는다 (기다리는 동안 커밋된 세션 폐기를 반영)
    SELECT * INTO v_sess FROM game_session gs WHERE gs.session_id = v_session_id;
    SELECT ps.allows_transfer INTO v_allows FROM protection_state ps WHERE ps.state_code = v_acc.state_code;

    v_reason := CASE
        WHEN v_sess.revoked_at IS NOT NULL                                   THEN 'SESSION_REVOKED'
        WHEN v_sess.expires_at <= now()                                      THEN 'SESSION_EXPIRED'
        WHEN v_sess.issued_credential_version <> v_acc.credential_version     THEN 'CREDENTIAL_ROTATED'
        WHEN NOT v_allows                                                    THEN 'STATE_BLOCKED'
        WHEN NOT v_tradable                                                  THEN 'NOT_TRADABLE'
    END;

    IF v_reason IS NULL THEN
        -- 조건부 UPDATE: 같은 아이템을 동시에 두 번 보내도 한 번만 성공한다
        UPDATE item i SET owner_account_id = p_to_account_id
         WHERE i.item_id = p_item_id AND i.owner_account_id = v_from;
        GET DIAGNOSTICS v_moved = ROW_COUNT;
        IF v_moved = 0 THEN
            v_reason := 'NOT_OWNER';
        END IF;
    END IF;

    INSERT INTO item_transfer (item_id, to_account_id, session_id, reject_reason)   -- result 는 생성 컬럼
    VALUES (p_item_id, p_to_account_id, v_session_id, v_reason)
    RETURNING item_transfer.transfer_id INTO v_id;

    RETURN QUERY SELECT v_id, CASE WHEN v_reason IS NULL THEN 'APPROVED' ELSE 'REJECTED' END, v_reason;
END $$;
