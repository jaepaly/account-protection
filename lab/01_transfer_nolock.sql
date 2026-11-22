-- =====================================================================
-- lab/01_transfer_nolock.sql — 13주 경합 실험용 '일부러 취약한' 아이템 이동 함수
-- 실행 역할: ap_owner. 운영·게임 역할에는 실행 권한을 주지 않는다.
--
-- ap.transfer_item 과 다른 점은 두 가지뿐이다.
--   ① 보내는 계정 행을 잠그지 않는다 (FOR SHARE 없음)
--   ② 검사와 실행 사이에 지연(p_delay_ms)을 넣어 경합 구간을 재현한다
-- 기대 결과: 지연 중에 '보호' 전이가 커밋되면, 이 함수는 이미 끝난 검사 결과를 믿고
--   아이템을 옮긴다. 보호 전이의 자산 스냅샷에는 그 아이템이 '보유 중'으로 남는데 실제
--   소유자는 바뀌어 있다 → 두 트랜잭션을 어떤 순서로 실행해도 나올 수 없는 결과(write skew).
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS lab;
REVOKE ALL ON SCHEMA lab FROM PUBLIC;
SET search_path = ap, ext;

CREATE OR REPLACE FUNCTION lab.transfer_item_nolock(p_session_token text,
                                                    p_item_id       bigint,
                                                    p_to_account_id bigint,
                                                    p_delay_ms      integer DEFAULT 0)
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
    SELECT it.is_tradable INTO v_tradable
      FROM item i JOIN item_template it ON it.template_id = i.template_id WHERE i.item_id = p_item_id;

    SELECT * INTO v_acc FROM account a WHERE a.account_id = v_from;            -- ① 잠금 없음
    SELECT * INTO v_sess FROM game_session gs WHERE gs.session_id = v_session_id;
    SELECT ps.allows_transfer INTO v_allows FROM protection_state ps WHERE ps.state_code = v_acc.state_code;

    v_reason := CASE
        WHEN v_sess.revoked_at IS NOT NULL                               THEN 'SESSION_REVOKED'
        WHEN v_sess.expires_at <= now()                                  THEN 'SESSION_EXPIRED'
        WHEN v_sess.issued_credential_version <> v_acc.credential_version THEN 'CREDENTIAL_ROTATED'
        WHEN NOT v_allows                                                THEN 'STATE_BLOCKED'
        WHEN NOT v_tradable                                              THEN 'NOT_TRADABLE'
    END;

    PERFORM pg_sleep(p_delay_ms / 1000.0);                                    -- ② 검사~실행 사이 지연

    IF v_reason IS NULL THEN
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

REVOKE EXECUTE ON FUNCTION lab.transfer_item_nolock(text, bigint, bigint, integer) FROM PUBLIC;
