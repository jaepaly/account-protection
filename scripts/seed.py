"""1단계(기능 검증) 합성 데이터 생성·적재.

    python scripts/seed.py                    # 기본: 계정 1,500 / 30일치 이력
    python scripts/seed.py --accounts 2000 --days 30 --seed 7

- 모든 값은 합성이다. 이메일은 example.com, IP는 사설(10.x)·문서용 대역(198.51.100.x, 203.0.113.x)만 쓴다.
- 대량 적재는 COPY 로 한다. 시드 계정 비밀번호는 'pw-<login_id>' (로컬 테스트용, bcrypt 비용 4).
- 과거 이력은 함수를 거치지 않고 직접 적재하므로, 적재 후 detect_risks() 로 위험 신호를 만든다.
- 탈취 시나리오의 정답 라벨은 data/seed_scenarios.csv 에 따로 저장한다 (DB에는 넣지 않음).

과거 이력 계정은 모두 '정상' 상태로 끝난다. 상태 전이는 운영 화면에서 실제 함수로 일으킨다.
"""
import argparse
import csv
import hashlib
import random
import sys
from datetime import datetime, timedelta, timezone

from dbconf import ROOT, connect, db_name

PLATFORMS = ['ANDROID', 'ANDROID', 'IOS', 'WINDOWS', 'WINDOWS', 'MAC']
SESSION_TTL = timedelta(hours=12)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Builder:
    def __init__(self, n_accounts: int, days: int, rng: random.Random, now: datetime):
        self.rng, self.now, self.start = rng, now, now - timedelta(days=days)
        self.days = days
        self.n_accounts = n_accounts
        self.accounts, self.devices, self.account_devices = [], [], {}
        self.sessions, self.attempts, self.items, self.transfers, self.scenarios = [], [], [], [], []
        self.owned = {}               # account_id -> set(item_id) (이동 재생용)

    # --- id 발급 (COPY 할 때 identity 를 OVERRIDING 하지 않도록 DB 기본값과 같은 1부터 순서대로)
    def new_device(self, key: str, platform: str, seen: datetime) -> int:
        self.devices.append((sha(key), platform, seen))
        return len(self.devices)

    def link(self, account_id: int, device_id: int, seen: datetime, trusted: bool):
        key = (account_id, device_id)
        if key in self.account_devices:
            first, last, tr, tr_at = self.account_devices[key]
            self.account_devices[key] = (min(first, seen), max(last, seen), tr, tr_at)
        else:
            self.account_devices[key] = (seen, seen, trusted, seen if trusted else None)

    def attempt(self, account_id, device_id, ip, at, ok, reason=None, revoked_logout=False):
        session_id = None
        if ok:
            self.link(account_id, device_id, at, trusted=False)
            expires = at + SESSION_TTL
            revoked = at + timedelta(minutes=self.rng.randint(5, 180)) if revoked_logout else None
            if revoked and revoked >= expires:
                revoked = None
            self.sessions.append((sha(f'token-{len(self.sessions)}-{at.isoformat()}'), account_id, device_id, ip,
                                  1, at, expires, revoked, 'LOGOUT' if revoked else None))
            session_id = len(self.sessions)
        self.attempts.append((account_id, device_id, ip, at, ok, reason, session_id))
        return session_id

    def rand_time(self, lo: datetime, hi: datetime) -> datetime:
        return lo + timedelta(seconds=self.rng.uniform(0, (hi - lo).total_seconds()))

    # --- 생성
    def build(self, n_templates: int, tradable_templates: list):
        rng = self.rng
        legit_ip = lambda: f'10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}'

        for n in range(1, self.n_accounts + 1):
            login_id = f'user{n:05d}'
            created = self.start - timedelta(days=rng.randint(30, 400))
            self.accounts.append((login_id, f'플레이어{n:05d}', f'{login_id}@example.com', f'pw-{login_id}', created))
            home_ip = legit_ip()
            devs = []
            for d in range(rng.choice([1, 1, 2, 2, 3])):
                dev = self.new_device(f'{login_id}-device-{d}', rng.choice(PLATFORMS), created)
                self.link(n, dev, created, trusted=True)
                devs.append(dev)
            # 아이템: 3~7개 (등급 가중치는 템플릿 순서로 대신 — 앞쪽이 흔함)
            self.owned[n] = set()
            for _ in range(rng.randint(3, 7)):
                tpl = min(int(rng.expovariate(0.25)) + 1, n_templates)
                self.items.append((tpl, n, created))
                self.owned[n].add(len(self.items))
            # 정상 로그인 이력: 60% 활성 계정, 하루 평균 0.6회
            if rng.random() < 0.6:
                day = self.start
                while day < self.now:
                    if rng.random() < 0.6:
                        at = day + timedelta(hours=rng.choice([8, 12, 19, 20, 21, 22]), minutes=rng.randint(0, 59))
                        if at < self.now:
                            dev = rng.choice(devs)
                            if rng.random() < 0.05:   # 오타 1~2회
                                for k in range(rng.randint(1, 2)):
                                    self.attempt(n, dev, home_ip, at - timedelta(seconds=20 * (k + 1)), False, 'BAD_PASSWORD')
                            self.attempt(n, dev, home_ip, at, True, revoked_logout=rng.random() < 0.3)
                    day += timedelta(days=1)

        # 정상 거래 (활성 세션 중에 같은 계정끼리)
        for _ in range(int(self.n_accounts * 0.8)):
            sid = rng.randrange(len(self.sessions)) + 1
            s = self.sessions[sid - 1]
            sender, at = s[1], s[5] + timedelta(minutes=rng.randint(1, 50))
            self.queue_transfer(sid, sender, rng.randint(1, self.n_accounts), at, tradable_templates)

        # 크리덴셜 스터핑 잡음: 공격 기기가 여러 계정을 1~3회씩만 찔러본다 (규칙 임계치 미만)
        attack_devs = [self.new_device(f'attacker-{k}', rng.choice(['WINDOWS', 'OTHER']), self.start)
                       for k in range(12)]
        attack_ip = lambda: f'203.0.113.{rng.randint(1, 254)}'
        for _ in range(self.n_accounts * 4):
            n = rng.randint(1, self.n_accounts)
            dev, ip, at = rng.choice(attack_devs), attack_ip(), self.rand_time(self.start, self.now)
            for k in range(rng.randint(1, 3)):
                self.attempt(n, dev, ip, at + timedelta(minutes=7 * k), False, 'BAD_PASSWORD')

        # 탈취 시나리오 (정답 라벨 기록)
        victims = rng.sample(range(1, self.n_accounts + 1), 27)
        mules = rng.sample([i for i in range(1, self.n_accounts + 1) if i not in victims], 4)
        plan = (['TAKEOVER'] * 10 + ['TAKEOVER_RECENT'] * 3 + ['BURST_ONLY'] * 6
                + ['SILENT_TAKEOVER'] * 2 + ['BENIGN_NEW_DEVICE'] * 6)
        for victim, kind in zip(victims, plan):
            dev, ip = rng.choice(attack_devs), attack_ip()
            if kind == 'TAKEOVER_RECENT':
                at = self.now - timedelta(hours=rng.uniform(1, 5))      # 공격자 세션이 아직 살아 있다
            else:
                at = self.rand_time(self.start + timedelta(days=1), self.now - timedelta(hours=13))
            if kind in ('TAKEOVER', 'TAKEOVER_RECENT', 'BURST_ONLY'):
                for k in range(rng.randint(6, 12)):
                    self.attempt(victim, dev, ip, at + timedelta(seconds=25 * k), False, 'BAD_PASSWORD')
                at += timedelta(minutes=6)
            if kind == 'BENIGN_NEW_DEVICE':
                dev = self.new_device(f'user{victim:05d}-new-phone', rng.choice(['ANDROID', 'IOS']), at)
                ip = legit_ip()
            if kind != 'BURST_ONLY':
                sid = self.attempt(victim, dev, ip, at, True)
            if kind in ('TAKEOVER', 'TAKEOVER_RECENT', 'SILENT_TAKEOVER'):
                mule = rng.choice(mules)
                for m in range(rng.randint(1, 3)):
                    self.queue_transfer(sid, victim, mule, at + timedelta(minutes=3 + 4 * m), tradable_templates,
                                        prefer_rare=True)
            self.scenarios.append((f'user{victim:05d}', victim, kind, at.isoformat(), f'mule:user{mule:05d}'
                                   if kind in ('TAKEOVER', 'TAKEOVER_RECENT', 'SILENT_TAKEOVER') else ''))

    def queue_transfer(self, session_id, sender, receiver, at, tradable_templates, prefer_rare=False):
        if sender == receiver:
            return
        self.transfers.append([session_id, sender, receiver, at, prefer_rare])

    def replay_transfers(self):
        """시간순으로 소유권을 갱신하며 실제로 가능한 이동만 남긴다."""
        rows = []
        for session_id, sender, receiver, at, prefer_rare in sorted(self.transfers, key=lambda r: r[3]):
            s = self.sessions[session_id - 1]
            if at >= s[6] or (s[7] and at >= s[7]) or at >= self.now:
                continue
            candidates = sorted(i for i in self.owned[sender] if self.items[i - 1][0] in self.tradable)
            if not candidates:
                continue
            item = max(candidates, key=lambda i: self.items[i - 1][0]) if prefer_rare else self.rng.choice(candidates)
            self.owned[sender].discard(item)
            self.owned[receiver].add(item)
            rows.append((item, receiver, session_id, at, at, None))          # 승인 (reject_reason 없음)
        final_owner = {i: acc for acc, its in self.owned.items() for i in its}
        self.items = [(tpl, final_owner[i + 1], acquired) for i, (tpl, _, acquired) in enumerate(self.items)]
        return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--accounts', type=int, default=1500)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--target', choices=['dev', 'test'], default='dev')
    args = parser.parse_args()
    dbname = db_name(args.target)

    with connect('ap_owner', dbname) as conn:
        if conn.execute('SELECT count(*) FROM ap.account').fetchone()[0]:
            print('ap.account 에 이미 데이터가 있습니다. scripts/apply.py --reset 후 다시 실행하세요.')
            return 1
        now = conn.execute("SELECT date_trunc('minute', now())").fetchone()[0].astimezone(timezone.utc)
        templates = conn.execute('SELECT template_id, is_tradable FROM ap.item_template ORDER BY template_id').fetchall()

        b = Builder(args.accounts, args.days, random.Random(args.seed), now)
        b.tradable = {t for t, ok in templates if ok}
        b.build(len(templates), b.tradable)
        transfers = b.replay_transfers()

        with conn.transaction():
            with conn.cursor() as cur:
                # 계정: 평문 비밀번호는 임시 테이블에만 두고 DB 안에서 bcrypt 로 변환
                cur.execute('CREATE TEMP TABLE seed_account (login_id text, nickname text, email text, pw text, created timestamptz) ON COMMIT DROP')
                with cur.copy('COPY seed_account FROM STDIN') as cp:
                    for row in b.accounts:
                        cp.write_row(row)
                cur.execute("""INSERT INTO ap.account (login_id, nickname, email, password_hash, created_at)
                               SELECT login_id, nickname, email, ext.crypt(pw, ext.gen_salt('bf', 4)), created
                               FROM seed_account ORDER BY login_id""")
                cur.execute("""INSERT INTO ap.credential_history (account_id, version, reason, changed_at)
                               SELECT account_id, 1, 'INITIAL', created_at FROM ap.account""")
                copies = [
                    ('ap.device (fingerprint, platform, first_seen_at)', b.devices),
                    # is_trusted, revoke_reason, success, result 는 생성 컬럼이라 넣지 않는다
                    ('ap.account_device (account_id, device_id, first_seen_at, last_seen_at, trusted_at)',
                     [(a, d, first, last, tr_at) for (a, d), (first, last, _, tr_at) in sorted(b.account_devices.items())]),
                    ('ap.game_session (token_hash, account_id, device_id, ip_address, issued_credential_version, '
                     'issued_at, expires_at, revoked_at)', [s[:8] for s in b.sessions]),
                    ('ap.login_attempt (account_id, device_id, ip_address, attempted_at, failure_reason, session_id)',
                     [(a, d, ip, at, reason, sid) for a, d, ip, at, _, reason, sid in b.attempts]),
                    ('ap.item (template_id, owner_account_id, acquired_at)', b.items),
                    ('ap.item_transfer (item_id, to_account_id, session_id, requested_at, decided_at, reject_reason)',
                     transfers),
                ]
                for target, rows in copies:
                    with cur.copy(f'COPY {target} FROM STDIN') as cp:
                        for row in rows:
                            cp.write_row(row)
            signals = conn.execute('SELECT ap.detect_risks()').fetchone()[0]
        conn.execute('ANALYZE')

        counts = conn.execute("""SELECT (SELECT count(*) FROM ap.account), (SELECT count(*) FROM ap.device),
                                        (SELECT count(*) FROM ap.game_session), (SELECT count(*) FROM ap.login_attempt),
                                        (SELECT count(*) FROM ap.item), (SELECT count(*) FROM ap.item_transfer)""").fetchone()

    out = ROOT / 'data' / 'seed_scenarios.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['login_id', 'account_id', 'scenario', 'started_at', 'note'])
        w.writerows(b.scenarios)

    print('accounts={} devices={} sessions={} login_attempts={} items={} transfers={} risk_signals={}'
          .format(*counts, signals))
    print(f'scenario labels -> {out.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
