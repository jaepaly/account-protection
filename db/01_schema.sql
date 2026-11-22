-- =====================================================================
-- 01_schema.sql — 계정 보호 상태기계: 테이블·제약조건·인덱스
-- 실행 역할: ap_owner (스키마 소유자)
--
-- 제약 이름 규칙: pk_ / uk_ / fk_ / ck_ + 테이블 + 의미
--
-- 참조 무결성 정책
--   ON DELETE RESTRICT : 감사 기록을 보존한다. 부모 행은 지우지 않고 상태로 표시한다
--                        (계정 = 영구 잠금, 운영자 = is_active, 규칙 = is_enabled, 세션 = revoked_at, 케이스 = closed_at).
--   ON DELETE CASCADE  : burst_signal → risk_signal 하나뿐. 하위 타입 행은 상위 행의 일부라 함께 지워진다.
--   SET NULL 은 쓰지 않는다. NULL 에 이미 다른 의미(시스템 자동 전이, 미처리 신호, 로그아웃 폐기)가 있어
--                        부모가 지워졌을 때 NULL 로 바꾸면 기록이 다른 뜻으로 읽힌다.
--   ON UPDATE RESTRICT : 키는 대리키(IDENTITY)이거나 함수·CHECK 가 참조하는 코드값이라 바꾸지 않는다.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS ext;                       -- 확장 모듈 전용 스키마
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA ext;    -- crypt()(bcrypt), digest()(SHA-256), gen_random_bytes()
CREATE SCHEMA IF NOT EXISTS ap;                        -- 도메인 테이블 (account protection)
SET search_path = ap, ext;

-- ---------------------------------------------------------------------
-- 1. 보호 상태 (참조 테이블) — 상태별 정책을 데이터로 정의
-- ---------------------------------------------------------------------
CREATE TABLE protection_state (
    state_code      varchar(16) NOT NULL,
    label_ko        varchar(20) NOT NULL,
    allows_login    boolean     NOT NULL,   -- 이 상태에서 새 로그인(세션 발급) 허용?
    allows_transfer boolean     NOT NULL,   -- 이 상태에서 아이템 이동 허용?
    closes_case     boolean     NOT NULL,   -- 이 상태로 들어가면 보호 케이스 종료? (정상 복귀·영구 잠금)
    sort_order      smallint    NOT NULL,
    CONSTRAINT pk_protection_state       PRIMARY KEY (state_code),
    CONSTRAINT uk_protection_state_label UNIQUE (label_ko),
    CONSTRAINT uk_protection_state_sort  UNIQUE (sort_order)
);

-- ---------------------------------------------------------------------
-- 2. 허용 전이 — 상태의 자기참조 M:N + 전이별 필수 동반 조치
--    여기에 없는 전이는 함수·트리거·FK 세 곳에서 모두 거부된다.
-- ---------------------------------------------------------------------
CREATE TABLE allowed_transition (
    from_state        varchar(16)  NOT NULL,
    to_state          varchar(16)  NOT NULL,
    revoke_sessions   boolean      NOT NULL DEFAULT false,  -- 활성 세션 전부 폐기
    rotate_credential boolean      NOT NULL DEFAULT false,  -- 자격증명 버전 증가 + 비밀번호 무효화
    snapshot_assets   boolean      NOT NULL DEFAULT false,  -- 보유 아이템 목록 동결
    description       varchar(200) NOT NULL,
    CONSTRAINT pk_allowed_transition          PRIMARY KEY (from_state, to_state),
    CONSTRAINT fk_allowed_transition_from     FOREIGN KEY (from_state) REFERENCES protection_state (state_code)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_allowed_transition_to       FOREIGN KEY (to_state) REFERENCES protection_state (state_code)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_allowed_transition_distinct CHECK (from_state <> to_state)
);

-- ---------------------------------------------------------------------
-- 3. 운영자 — 웹 로그인은 Django 기본 인증, 여기서는 행위 주체 식별용
-- ---------------------------------------------------------------------
CREATE TABLE operator (
    operator_id  integer GENERATED ALWAYS AS IDENTITY,
    username     varchar(150) NOT NULL,                  -- Django auth_user.username 과 매핑
    display_name varchar(50)  NOT NULL,
    is_active    boolean      NOT NULL DEFAULT true,     -- 퇴사·권한 회수는 삭제가 아니라 false
    created_at   timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_operator          PRIMARY KEY (operator_id),
    CONSTRAINT uk_operator_username UNIQUE (username)
);

-- ---------------------------------------------------------------------
-- 4. 게임 계정
-- ---------------------------------------------------------------------
CREATE TABLE account (
    account_id         bigint GENERATED ALWAYS AS IDENTITY,
    login_id           varchar(30)  NOT NULL,
    nickname           varchar(30)  NOT NULL,
    email              varchar(254) NOT NULL,          -- 개인정보: 운영 역할은 마스킹된 뷰로만 조회
    password_hash      text,                           -- bcrypt. NULL = 자격증명 폐기됨(재설정 대기)
    credential_version integer      NOT NULL DEFAULT 1,
    state_code         varchar(16)  NOT NULL DEFAULT 'NORMAL',
    created_at         timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_account                    PRIMARY KEY (account_id),
    CONSTRAINT uk_account_login_id           UNIQUE (login_id),
    CONSTRAINT uk_account_nickname           UNIQUE (nickname),
    CONSTRAINT fk_account_state              FOREIGN KEY (state_code) REFERENCES protection_state (state_code)
                                             ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_account_credential_version CHECK (credential_version >= 1),
    -- 정책: 정상·의심 상태(=로그인 가능 상태)의 계정은 반드시 비밀번호가 있어야 한다.
    --       → 복구 중에 새 비밀번호를 정하지 않으면 '정상'으로 돌아갈 수 없다.
    CONSTRAINT ck_account_password_required
        CHECK (password_hash IS NOT NULL OR state_code IN ('PROTECTED', 'RECOVERING', 'LOCKED'))
);

-- ---------------------------------------------------------------------
-- 5. 자격증명 변경 이력 (약한 엔티티: 계정 + 버전)
-- ---------------------------------------------------------------------
CREATE TABLE credential_history (
    account_id  bigint      NOT NULL,
    version     integer     NOT NULL,
    reason      varchar(20) NOT NULL,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    operator_id integer,                               -- 운영자 조치로 바뀐 경우 (NULL = 이용자 본인·최초 설정)
    CONSTRAINT pk_credential_history          PRIMARY KEY (account_id, version),
    CONSTRAINT fk_credential_history_account  FOREIGN KEY (account_id) REFERENCES account (account_id)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_credential_history_operator FOREIGN KEY (operator_id) REFERENCES operator (operator_id)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_credential_history_version  CHECK (version >= 1),
    CONSTRAINT ck_credential_history_reason   CHECK (reason IN ('INITIAL', 'USER_CHANGE', 'FORCED_ROTATION', 'RECOVERY_RESET'))
);

-- 계정의 현재 자격증명 버전은 반드시 이력에 존재해야 한다.
-- account ↔ credential_history 가 서로를 참조(순환)하므로 커밋 시점에 검사(DEFERRABLE).
ALTER TABLE account
    ADD CONSTRAINT fk_account_current_credential
    FOREIGN KEY (account_id, credential_version)
    REFERENCES credential_history (account_id, version)
    ON DELETE RESTRICT ON UPDATE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

-- ---------------------------------------------------------------------
-- 6. 기기 — 클라이언트 기기 식별값의 SHA-256만 저장 (원문 비저장)
-- ---------------------------------------------------------------------
CREATE TABLE device (
    device_id     bigint GENERATED ALWAYS AS IDENTITY,
    fingerprint   char(64)    NOT NULL,
    platform      varchar(10) NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_device             PRIMARY KEY (device_id),
    CONSTRAINT uk_device_fingerprint UNIQUE (fingerprint),
    CONSTRAINT ck_device_platform    CHECK (platform IN ('WINDOWS', 'MAC', 'ANDROID', 'IOS', 'OTHER')),
    CONSTRAINT ck_device_fingerprint_hex CHECK (fingerprint ~ '^[0-9a-f]{64}$')   -- char(64) 는 짧은 값을 공백으로 채워 받아들이므로 형식 검사
);

-- ---------------------------------------------------------------------
-- 7. 계정–기기 신뢰 관계 (M:N)
-- ---------------------------------------------------------------------
CREATE TABLE account_device (
    account_id    bigint      NOT NULL,
    device_id     bigint      NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    trusted_at    timestamptz,                -- NULL = 신뢰하지 않는 기기
    is_trusted    boolean     NOT NULL GENERATED ALWAYS AS (trusted_at IS NOT NULL) STORED,   -- 유도 컬럼 (DBMS 계산)
    CONSTRAINT pk_account_device            PRIMARY KEY (account_id, device_id),
    CONSTRAINT fk_account_device_account    FOREIGN KEY (account_id) REFERENCES account (account_id)
                                            ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_account_device_device     FOREIGN KEY (device_id) REFERENCES device (device_id)
                                            ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_account_device_seen_order CHECK (last_seen_at >= first_seen_at)
);
CREATE INDEX account_device_device_idx ON account_device (device_id);   -- 한 기기를 쓰는 계정들 역조회

-- ---------------------------------------------------------------------
-- 8. 보호 케이스 — 계정이 '정상'을 벗어나 다시 돌아오거나 잠길 때까지의 사건 단위
-- ---------------------------------------------------------------------
CREATE TABLE protection_case (
    case_id    bigint GENERATED ALWAYS AS IDENTITY,
    account_id bigint      NOT NULL,
    opened_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    closed_at  timestamptz,                   -- NULL = 진행 중
    CONSTRAINT pk_protection_case         PRIMARY KEY (case_id),
    CONSTRAINT fk_protection_case_account FOREIGN KEY (account_id) REFERENCES account (account_id)
                                          ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_protection_case_period  CHECK (closed_at IS NULL OR closed_at >= opened_at)
);
-- 계정당 열린 케이스는 최대 1개 (부분 유니크 인덱스)
CREATE UNIQUE INDEX uk_protection_case_one_open ON protection_case (account_id) WHERE closed_at IS NULL;
CREATE INDEX protection_case_account_idx ON protection_case (account_id, opened_at);

-- ---------------------------------------------------------------------
-- 9. 케이스 내 상태 전이 기록 (약한 엔티티: 케이스 + 순번)
-- ---------------------------------------------------------------------
CREATE TABLE case_transition (
    case_id         bigint       NOT NULL,
    seq             smallint     NOT NULL,
    from_state      varchar(16)  NOT NULL,
    to_state        varchar(16)  NOT NULL,
    operator_id     integer,                                -- NULL = 시스템 자동 전이 (확장 기능용)
    reason          varchar(500) NOT NULL,
    transitioned_at timestamptz  NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_case_transition          PRIMARY KEY (case_id, seq),
    CONSTRAINT fk_case_transition_case     FOREIGN KEY (case_id) REFERENCES protection_case (case_id)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_case_transition_allowed  FOREIGN KEY (from_state, to_state)                   -- 허용 전이만 기록 가능
                                           REFERENCES allowed_transition (from_state, to_state)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_case_transition_operator FOREIGN KEY (operator_id) REFERENCES operator (operator_id)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_case_transition_seq      CHECK (seq >= 1),
    CONSTRAINT ck_case_transition_reason   CHECK (length(btrim(reason)) > 0)
);

-- ---------------------------------------------------------------------
-- 10. 게임 세션 — 토큰 원문은 저장하지 않고 SHA-256만
--     유효 조건: 미폐기 AND 미만료 AND 발급 시 자격증명 버전 = 계정의 현재 버전
-- ---------------------------------------------------------------------
CREATE TABLE game_session (
    session_id                bigint GENERATED ALWAYS AS IDENTITY,
    token_hash                char(64)    NOT NULL,
    account_id                bigint      NOT NULL,
    device_id                 bigint      NOT NULL,
    ip_address                inet        NOT NULL,
    issued_credential_version integer     NOT NULL,
    issued_at                 timestamptz NOT NULL DEFAULT now(),
    expires_at                timestamptz NOT NULL,
    revoked_at                timestamptz,
    revoked_case_id           bigint,      -- 상태 전이로 폐기된 경우: 어떤 전이가 끊었는지 (없으면 로그아웃)
    revoked_seq               smallint,
    revoke_reason             varchar(20) GENERATED ALWAYS AS (            -- 유도 컬럼 (DBMS 계산). NULL = 폐기되지 않음
                                  (CASE WHEN revoked_at IS NULL THEN NULL
                                        WHEN revoked_case_id IS NULL THEN 'LOGOUT'
                                        ELSE 'STATE_TRANSITION' END)::varchar(20)) STORED,
    CONSTRAINT pk_game_session                PRIMARY KEY (session_id),
    CONSTRAINT uk_game_session_token          UNIQUE (token_hash),
    CONSTRAINT fk_game_session_account_device FOREIGN KEY (account_id, device_id)               -- 등록된 계정-기기 쌍에서만 발급
                                              REFERENCES account_device (account_id, device_id)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_game_session_credential     FOREIGN KEY (account_id, issued_credential_version)
                                              REFERENCES credential_history (account_id, version)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_game_session_revoked_by     FOREIGN KEY (revoked_case_id, revoked_seq)
                                              REFERENCES case_transition (case_id, seq)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_game_session_token_hex      CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_game_session_expiry         CHECK (expires_at > issued_at),
    CONSTRAINT ck_game_session_revoked_time   CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    CONSTRAINT ck_game_session_revoked_pair   CHECK ((revoked_case_id IS NULL) = (revoked_seq IS NULL)),
    CONSTRAINT ck_game_session_revoked_by     CHECK (revoked_case_id IS NULL OR revoked_at IS NOT NULL)   -- 전이가 끊었다면 폐기 일시가 있어야 한다
);
CREATE INDEX game_session_account_idx ON game_session (account_id, issued_at);
CREATE INDEX game_session_active_idx  ON game_session (account_id) WHERE revoked_at IS NULL;   -- 폐기 대상 탐색

-- ---------------------------------------------------------------------
-- 11. 로그인 시도
-- ---------------------------------------------------------------------
CREATE TABLE login_attempt (
    attempt_id     bigint GENERATED ALWAYS AS IDENTITY,
    account_id     bigint      NOT NULL,
    device_id      bigint      NOT NULL,
    ip_address     inet        NOT NULL,
    attempted_at   timestamptz NOT NULL DEFAULT now(),
    failure_reason varchar(24),                                  -- NULL = 성공
    session_id     bigint,                                       -- 성공 시 발급된 세션 (NULL = 실패)
    success        boolean     NOT NULL GENERATED ALWAYS AS (failure_reason IS NULL) STORED,   -- 유도 컬럼 (DBMS 계산)
    CONSTRAINT pk_login_attempt                 PRIMARY KEY (attempt_id),
    CONSTRAINT uk_login_attempt_session         UNIQUE (session_id),
    CONSTRAINT fk_login_attempt_account         FOREIGN KEY (account_id) REFERENCES account (account_id)
                                                ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_login_attempt_device          FOREIGN KEY (device_id) REFERENCES device (device_id)
                                                ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_login_attempt_session         FOREIGN KEY (session_id) REFERENCES game_session (session_id)
                                                ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_login_attempt_failure_reason  CHECK (failure_reason IN ('BAD_PASSWORD', 'STATE_BLOCKED', 'PASSWORD_RESET_REQUIRED')),
    CONSTRAINT ck_login_attempt_session_success CHECK ((failure_reason IS NULL) = (session_id IS NOT NULL))   -- 성공한 시도에만 세션이 있다
);
-- 탐지 규칙·타임라인의 핵심 접근 경로 (13주 인덱스 실험 대상)
CREATE INDEX login_attempt_account_time_idx ON login_attempt (account_id, attempted_at);

-- ---------------------------------------------------------------------
-- 12. 탐지 규칙 — 임계치를 코드가 아니라 데이터로
-- ---------------------------------------------------------------------
CREATE TABLE risk_rule (
    rule_code      varchar(20) NOT NULL,
    name_ko        varchar(40) NOT NULL,
    window_minutes integer,                              -- NULL = 기간을 쓰지 않는 규칙
    threshold      integer,                              -- NULL = 임계치를 쓰지 않는 규칙
    severity       smallint    NOT NULL,
    is_enabled     boolean     NOT NULL DEFAULT true,    -- 규칙 폐지는 삭제가 아니라 false
    CONSTRAINT pk_risk_rule           PRIMARY KEY (rule_code),
    CONSTRAINT ck_risk_rule_window    CHECK (window_minutes > 0),
    CONSTRAINT ck_risk_rule_threshold CHECK (threshold > 0),
    CONSTRAINT ck_risk_rule_severity  CHECK (severity BETWEEN 1 AND 3),
    -- 실패 폭주 규칙은 기간·임계치가 반드시 있어야 한다 (NULL 이면 탐지 함수가 실패해 로그인까지 막힌다)
    CONSTRAINT ck_risk_rule_burst_params
        CHECK (rule_code <> 'FAILED_BURST' OR (window_minutes IS NOT NULL AND threshold IS NOT NULL))
);

-- ---------------------------------------------------------------------
-- 13. 위험 신호 — 계정·발생 시각·기기는 원인 로그인 시도에서 얻는다 (중복 저장하지 않음)
-- ---------------------------------------------------------------------
CREATE TABLE risk_signal (
    signal_id          bigint GENERATED ALWAYS AS IDENTITY,
    rule_code          varchar(20) NOT NULL,
    trigger_attempt_id bigint      NOT NULL,
    detected_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
    case_id            bigint,                                     -- 케이스가 열리면 연결 (NULL = 미처리)
    CONSTRAINT pk_risk_signal              PRIMARY KEY (signal_id),
    CONSTRAINT uk_risk_signal_rule_attempt UNIQUE (rule_code, trigger_attempt_id),   -- 같은 원인으로 중복 신호 금지
    CONSTRAINT uk_risk_signal_id_rule      UNIQUE (signal_id, rule_code),            -- 하위 타입(burst_signal)이 규칙까지 함께 참조
    CONSTRAINT fk_risk_signal_rule         FOREIGN KEY (rule_code) REFERENCES risk_rule (rule_code)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_risk_signal_attempt      FOREIGN KEY (trigger_attempt_id) REFERENCES login_attempt (attempt_id)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_risk_signal_case         FOREIGN KEY (case_id) REFERENCES protection_case (case_id)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT
);
CREATE INDEX risk_signal_case_idx ON risk_signal (case_id);
CREATE INDEX risk_signal_unassigned_idx ON risk_signal (trigger_attempt_id) WHERE case_id IS NULL;

-- ---------------------------------------------------------------------
-- 13-1. 실패 폭주 신호 (위험 신호의 하위 타입)
--   정규화: 예전 evidence(JSONB)에 묶여 있던 값을 원자값 컬럼으로 분리했다.
--   window_minutes 는 '탐지 당시' 적용된 기간이다. 규칙의 기간은 나중에 바뀔 수 있으므로
--   risk_rule 에서 유도되는 값이 아니라 이 신호의 사실이다.
--   rule_code 는 고정값 생성 컬럼: (signal_id, rule_code) 복합 FK 로 실패 폭주 신호에만 붙을 수 있다.
--   하위 타입 행은 상위 행의 일부이므로 상위 신호가 지워지면 함께 지워진다 (ON DELETE CASCADE).
-- ---------------------------------------------------------------------
CREATE TABLE burst_signal (
    signal_id          bigint      NOT NULL,
    rule_code          varchar(20) NOT NULL GENERATED ALWAYS AS ('FAILED_BURST') STORED,
    failures_in_window integer     NOT NULL,
    window_minutes     integer     NOT NULL,
    CONSTRAINT pk_burst_signal          PRIMARY KEY (signal_id),
    CONSTRAINT fk_burst_signal_signal   FOREIGN KEY (signal_id, rule_code) REFERENCES risk_signal (signal_id, rule_code)
                                        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT ck_burst_signal_failures CHECK (failures_in_window > 0),
    CONSTRAINT ck_burst_signal_window   CHECK (window_minutes > 0)
);

-- ---------------------------------------------------------------------
-- 14. 아이템 템플릿 — 이름·등급·거래 가능 여부는 종류에 따라 정해진다 (3NF 분해)
-- ---------------------------------------------------------------------
CREATE TABLE item_template (
    template_id integer GENERATED ALWAYS AS IDENTITY,
    name        varchar(50) NOT NULL,
    rarity      varchar(10) NOT NULL,
    is_tradable boolean     NOT NULL DEFAULT true,
    CONSTRAINT pk_item_template        PRIMARY KEY (template_id),
    CONSTRAINT uk_item_template_name   UNIQUE (name),
    CONSTRAINT ck_item_template_rarity CHECK (rarity IN ('COMMON', 'RARE', 'EPIC', 'LEGENDARY'))
);

-- ---------------------------------------------------------------------
-- 15. 아이템 (개별 인스턴스)
-- ---------------------------------------------------------------------
CREATE TABLE item (
    item_id          bigint GENERATED ALWAYS AS IDENTITY,
    template_id      integer     NOT NULL,
    owner_account_id bigint      NOT NULL,
    acquired_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_item          PRIMARY KEY (item_id),
    CONSTRAINT fk_item_template FOREIGN KEY (template_id) REFERENCES item_template (template_id)
                                ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_item_owner    FOREIGN KEY (owner_account_id) REFERENCES account (account_id)
                                ON DELETE RESTRICT ON UPDATE RESTRICT
);
CREATE INDEX item_owner_idx ON item (owner_account_id);

-- ---------------------------------------------------------------------
-- 16. 보호 진입 시점 보유 아이템 스냅샷 — 복구 기준선
-- ---------------------------------------------------------------------
CREATE TABLE case_asset_snapshot (
    case_id     bigint      NOT NULL,
    item_id     bigint      NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_case_asset_snapshot      PRIMARY KEY (case_id, item_id),
    CONSTRAINT fk_case_asset_snapshot_case FOREIGN KEY (case_id) REFERENCES protection_case (case_id)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_case_asset_snapshot_item FOREIGN KEY (item_id) REFERENCES item (item_id)
                                           ON DELETE RESTRICT ON UPDATE RESTRICT
);

-- ---------------------------------------------------------------------
-- 17. 아이템 이동 — 거절된 요청도 기록한다. 보낸 계정은 요청 세션에서 얻는다.
-- ---------------------------------------------------------------------
CREATE TABLE item_transfer (
    transfer_id   bigint GENERATED ALWAYS AS IDENTITY,
    item_id       bigint      NOT NULL,
    to_account_id bigint      NOT NULL,
    session_id    bigint      NOT NULL,
    requested_at  timestamptz NOT NULL DEFAULT now(),              -- 트랜잭션 시작 시각
    decided_at    timestamptz NOT NULL DEFAULT clock_timestamp(),  -- 판정 시각 (경합 실험의 기준)
    reject_reason varchar(20),                                     -- NULL = 승인
    result        varchar(10) NOT NULL GENERATED ALWAYS AS (             -- 유도 컬럼 (DBMS 계산)
                      (CASE WHEN reject_reason IS NULL THEN 'APPROVED' ELSE 'REJECTED' END)::varchar(10)) STORED,
    CONSTRAINT pk_item_transfer               PRIMARY KEY (transfer_id),
    CONSTRAINT fk_item_transfer_item          FOREIGN KEY (item_id) REFERENCES item (item_id)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_item_transfer_to_account    FOREIGN KEY (to_account_id) REFERENCES account (account_id)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_item_transfer_session       FOREIGN KEY (session_id) REFERENCES game_session (session_id)
                                              ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_item_transfer_reject_reason CHECK (reject_reason IN ('SESSION_REVOKED', 'SESSION_EXPIRED', 'CREDENTIAL_ROTATED',
                                                                       'STATE_BLOCKED', 'NOT_OWNER', 'NOT_TRADABLE')),
    CONSTRAINT ck_item_transfer_decided_time  CHECK (decided_at >= requested_at)
);
CREATE INDEX item_transfer_session_idx ON item_transfer (session_id);
CREATE INDEX item_transfer_item_idx    ON item_transfer (item_id, decided_at);
