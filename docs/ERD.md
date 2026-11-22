# ERD (물리 스키마)

`scripts/export_erd_mermaid.py`가 실제 DB 카탈로그(`docs/spec/phys_catalog.json`)에서 만든다. 손으로 그리지 않는다.

테이블 18개 · PK 18 · FK 29 · UNIQUE 11 + 부분 UNIQUE 1 · CHECK 27

실선은 식별 관계(외래키가 기본키의 일부), 점선은 비식별 관계다.

## 관계만

```mermaid
erDiagram
    protection_state ||--o{ allowed_transition : "from_state"
    protection_state ||--o{ allowed_transition : "to_state"
    credential_history ||..o| account : "account_id, credential_version"
    protection_state ||..o{ account : "state_code"
    account ||--o{ credential_history : "account_id"
    operator |o..o{ credential_history : "operator_id"
    account ||--o{ account_device : "account_id"
    device ||--o{ account_device : "device_id"
    account_device ||..o{ game_session : "account_id, device_id"
    credential_history ||..o{ game_session : "account_id, issued_credential_version"
    case_transition |o..o{ game_session : "revoked_case_id, revoked_seq"
    account ||..o{ login_attempt : "account_id"
    device ||..o{ login_attempt : "device_id"
    game_session |o..o| login_attempt : "session_id"
    login_attempt ||..o{ risk_signal : "trigger_attempt_id"
    protection_case |o..o{ risk_signal : "case_id"
    risk_rule ||..o{ risk_signal : "rule_code"
    risk_signal ||--o| burst_signal : "signal_id, rule_code"
    account ||..o{ protection_case : "account_id"
    allowed_transition ||..o{ case_transition : "from_state, to_state"
    protection_case ||--o{ case_transition : "case_id"
    operator |o..o{ case_transition : "operator_id"
    protection_case ||--o{ case_asset_snapshot : "case_id"
    item ||--o{ case_asset_snapshot : "item_id"
    account ||..o{ item : "owner_account_id"
    item_template ||..o{ item : "template_id"
    item ||..o{ item_transfer : "item_id"
    game_session ||..o{ item_transfer : "session_id"
    account ||..o{ item_transfer : "to_account_id"
```

## 컬럼 포함

```mermaid
erDiagram
    protection_state ||--o{ allowed_transition : "from_state"
    protection_state ||--o{ allowed_transition : "to_state"
    credential_history ||..o| account : "account_id, credential_version"
    protection_state ||..o{ account : "state_code"
    account ||--o{ credential_history : "account_id"
    operator |o..o{ credential_history : "operator_id"
    account ||--o{ account_device : "account_id"
    device ||--o{ account_device : "device_id"
    account_device ||..o{ game_session : "account_id, device_id"
    credential_history ||..o{ game_session : "account_id, issued_credential_version"
    case_transition |o..o{ game_session : "revoked_case_id, revoked_seq"
    account ||..o{ login_attempt : "account_id"
    device ||..o{ login_attempt : "device_id"
    game_session |o..o| login_attempt : "session_id"
    login_attempt ||..o{ risk_signal : "trigger_attempt_id"
    protection_case |o..o{ risk_signal : "case_id"
    risk_rule ||..o{ risk_signal : "rule_code"
    risk_signal ||--o| burst_signal : "signal_id, rule_code"
    account ||..o{ protection_case : "account_id"
    allowed_transition ||..o{ case_transition : "from_state, to_state"
    protection_case ||--o{ case_transition : "case_id"
    operator |o..o{ case_transition : "operator_id"
    protection_case ||--o{ case_asset_snapshot : "case_id"
    item ||--o{ case_asset_snapshot : "item_id"
    account ||..o{ item : "owner_account_id"
    item_template ||..o{ item : "template_id"
    item ||..o{ item_transfer : "item_id"
    game_session ||..o{ item_transfer : "session_id"
    account ||..o{ item_transfer : "to_account_id"
    protection_state {
        varchar(16) state_code PK
        varchar(20) label_ko UK
        boolean allows_login
        boolean allows_transfer
        boolean closes_case
        smallint sort_order UK
    }
    allowed_transition {
        varchar(16) from_state PK, FK
        varchar(16) to_state PK, FK
        boolean revoke_sessions
        boolean rotate_credential
        boolean snapshot_assets
        varchar(200) description
    }
    operator {
        integer operator_id PK "IDENTITY"
        varchar(150) username UK
        varchar(50) display_name
        boolean is_active
        timestamptz created_at
    }
    account {
        bigint account_id PK, FK "IDENTITY"
        varchar(30) login_id UK
        varchar(30) nickname UK
        varchar(254) email
        text password_hash "NULL 허용"
        integer credential_version FK
        varchar(16) state_code FK
        timestamptz created_at
    }
    credential_history {
        bigint account_id PK, FK
        integer version PK
        varchar(20) reason
        timestamptz changed_at
        integer operator_id FK "NULL 허용"
    }
    device {
        bigint device_id PK "IDENTITY"
        char(64) fingerprint UK
        varchar(10) platform
        timestamptz first_seen_at
    }
    account_device {
        bigint account_id PK, FK
        bigint device_id PK, FK
        timestamptz first_seen_at
        timestamptz last_seen_at
        timestamptz trusted_at "NULL 허용"
        boolean is_trusted "생성 컬럼"
    }
    game_session {
        bigint session_id PK "IDENTITY"
        char(64) token_hash UK
        bigint account_id FK
        bigint device_id FK
        inet ip_address
        integer issued_credential_version FK
        timestamptz issued_at
        timestamptz expires_at
        timestamptz revoked_at "NULL 허용"
        bigint revoked_case_id FK "NULL 허용"
        smallint revoked_seq FK "NULL 허용"
        varchar(20) revoke_reason "NULL 허용, 생성 컬럼"
    }
    login_attempt {
        bigint attempt_id PK "IDENTITY"
        bigint account_id FK
        bigint device_id FK
        inet ip_address
        timestamptz attempted_at
        varchar(24) failure_reason "NULL 허용"
        bigint session_id FK, UK "NULL 허용"
        boolean success "생성 컬럼"
    }
    risk_rule {
        varchar(20) rule_code PK
        varchar(40) name_ko
        integer window_minutes "NULL 허용"
        integer threshold "NULL 허용"
        smallint severity
        boolean is_enabled
    }
    risk_signal {
        bigint signal_id PK, UK "IDENTITY"
        varchar(20) rule_code FK, UK
        bigint trigger_attempt_id FK, UK
        timestamptz detected_at
        bigint case_id FK "NULL 허용"
    }
    burst_signal {
        bigint signal_id PK, FK
        varchar(20) rule_code FK "생성 컬럼"
        integer failures_in_window
        integer window_minutes
    }
    protection_case {
        bigint case_id PK "IDENTITY"
        bigint account_id FK
        timestamptz opened_at
        timestamptz closed_at "NULL 허용"
    }
    case_transition {
        bigint case_id PK, FK
        smallint seq PK
        varchar(16) from_state FK
        varchar(16) to_state FK
        integer operator_id FK "NULL 허용"
        varchar(500) reason
        timestamptz transitioned_at
    }
    case_asset_snapshot {
        bigint case_id PK, FK
        bigint item_id PK, FK
        timestamptz captured_at
    }
    item_template {
        integer template_id PK "IDENTITY"
        varchar(50) name UK
        varchar(10) rarity
        boolean is_tradable
    }
    item {
        bigint item_id PK "IDENTITY"
        integer template_id FK
        bigint owner_account_id FK
        timestamptz acquired_at
    }
    item_transfer {
        bigint transfer_id PK "IDENTITY"
        bigint item_id FK
        bigint to_account_id FK
        bigint session_id FK
        timestamptz requested_at
        timestamptz decided_at
        varchar(20) reject_reason "NULL 허용"
        varchar(10) result "생성 컬럼"
    }
```
