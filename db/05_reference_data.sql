-- =====================================================================
-- 05_reference_data.sql — 상태·전이 정책·탐지 규칙·아이템 종류·운영자
-- 실행 역할: ap_owner
-- =====================================================================
SET search_path = ap, ext;

INSERT INTO protection_state (state_code, label_ko, allows_login, allows_transfer, closes_case, sort_order) VALUES
    ('NORMAL',     '정상',      true,  true,  true,  1),
    ('SUSPECTED',  '의심',      true,  true,  false, 2),   -- 모니터링만: 오탐일 수 있으므로 이용은 막지 않는다
    ('PROTECTED',  '보호',      false, false, false, 3),
    ('RECOVERING', '복구 중',   false, false, false, 4),
    ('LOCKED',     '영구 잠금', false, false, true,  5);

--                          from          to           세션폐기 자격회전 자산동결
INSERT INTO allowed_transition (from_state, to_state, revoke_sessions, rotate_credential, snapshot_assets, description) VALUES
    ('NORMAL',     'SUSPECTED',  false, false, false, '위험 신호 확인 — 모니터링 시작'),
    ('NORMAL',     'PROTECTED',  true,  true,  true,  '이용자 신고 등으로 즉시 보호'),
    ('SUSPECTED',  'NORMAL',     false, false, false, '오탐 판정 — 정상 복귀'),
    ('SUSPECTED',  'PROTECTED',  true,  true,  true,  '탈취 판단 — 보호 조치'),
    ('PROTECTED',  'RECOVERING', false, false, false, '본인 확인 절차 시작'),
    ('RECOVERING', 'PROTECTED',  true,  false, false, '본인 확인 실패 — 보호로 되돌림'),
    ('RECOVERING', 'NORMAL',     false, false, false, '복구 완료 (새 비밀번호 필수)'),
    ('NORMAL',     'LOCKED',     true,  true,  true,  '영구 잠금'),
    ('SUSPECTED',  'LOCKED',     true,  true,  true,  '영구 잠금'),
    ('PROTECTED',  'LOCKED',     true,  true,  true,  '영구 잠금'),
    ('RECOVERING', 'LOCKED',     true,  true,  true,  '영구 잠금');

INSERT INTO risk_rule (rule_code, name_ko, window_minutes, threshold, severity) VALUES
    ('FAILED_BURST', '로그인 실패 폭주', 10,   5,    2),
    ('NEW_DEVICE',   '신규 기기 로그인', NULL, NULL, 1);

INSERT INTO item_template (name, rarity, is_tradable) VALUES
    ('낡은 단검',        'COMMON',    true),
    ('견습생의 지팡이',  'COMMON',    true),
    ('가죽 갑옷',        'COMMON',    true),
    ('체력 물약 묶음',   'COMMON',    true),
    ('강철 장검',        'RARE',      true),
    ('마력의 반지',      'RARE',      true),
    ('질풍의 장화',      'RARE',      true),
    ('수호자의 방패',    'RARE',      true),
    ('화염 마법서',      'EPIC',      true),
    ('그림자 망토',      'EPIC',      true),
    ('용비늘 갑옷',      'EPIC',      true),
    ('서리 활',          'EPIC',      true),
    ('여명의 검',        'LEGENDARY', true),
    ('심연의 왕관',      'LEGENDARY', true),
    ('창립 기념 칭호',   'EPIC',      false),     -- 귀속 아이템: 거래 불가
    ('시즌 1 우승 휘장', 'LEGENDARY', false);

INSERT INTO operator (username, display_name) VALUES
    ('op_kim',  '김운영'),
    ('op_lee',  '이보안'),
    ('op_park', '박관제');
