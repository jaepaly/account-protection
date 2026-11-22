"""EER 그림 정의.  python figures.py [이름 ...]  →  img/<이름>.png / .svg

그림 1  전체 EER       : 개체·관계·카디널리티·참여·특수화 (속성 생략) — ELK 자동 배치
그림 2~4 영역별 상세 EER : 속성 포함, 좌표 수동 배치. 다른 그림에서 정의한 개체는 점선·회색 '참조 개체'
"""
import sys

from eer import Fig, render_png

LAYOUT = {'elk.layered.thoroughness': '60', 'elk.layered.considerModelOrder.strategy': 'NONE',
          'elk.layered.crossingMinimization.greedySwitch.type': 'TWO_SIDED',
          'elk.spacing.edgeEdge': '24', 'elk.spacing.edgeNode': '22',
          'elk.layered.spacing.edgeNodeBetweenLayers': '24', 'elk.layered.spacing.edgeEdgeBetweenLayers': '20',
          'elk.layered.spacing.nodeNodeBetweenLayers': '50'}


def A(f: Fig, owner: str, *items):
    """속성 노드를 만들고 id 목록을 돌려준다. items: '이름' 또는 ('이름', 'key'|'partial'|'derived'|'multi')"""
    ids = []
    for i, it in enumerate(items):
        name, flag = (it, None) if isinstance(it, str) else it
        aid = f'{owner}__a{i}'
        f.attr(aid, name, key=flag == 'key', partial=flag == 'partial', derived=flag == 'derived', multi=flag == 'multi')
        ids.append(aid)
    f.has(owner, *ids)
    return ids


def put(f: Fig, positions: dict):
    for nid, (x, y) in positions.items():
        f.place(nid, x, y)


# ===================================================================== 그림 1
def overview() -> Fig:
    f = Fig()
    f.opts.update(LAYOUT)
    E = f.entity
    E('ACC', '계정'); E('DEV', '기기'); E('REG', '등록기기', weak=True); E('CRED', '자격증명이력', weak=True)
    E('SES', '게임세션'); E('SES_REV', '폐기세션'); E('LA', '로그인시도'); E('PS', '보호상태')
    E('AT', '허용전이', weak=True); E('CASE', '보호케이스'); E('CT', '상태전이기록', weak=True); E('OP', '운영자')
    E('RR', '탐지규칙'); E('RS', '위험신호'); E('IT', '아이템종류'); E('ITEM', '아이템'); E('TR', '아이템이동')
    E('LA_OK', '성공로그인'); E('LA_NO', '실패로그인')
    E('SES_LO', '로그아웃폐기세션'); E('SES_TR', '전이폐기세션')
    E('CS_OPEN', '진행중케이스'); E('CS_DONE', '종료케이스')
    E('TR_OK', '승인이동'); E('TR_NO', '거절이동')

    R = f.relate
    R('PS', '현재상태', 'ACC', total=(False, True))
    R('PS', '출발', 'AT', total=(False, True), ident=True)
    R('PS', '도착', 'AT', total=(False, True), ident=True)
    R('ACC', '자격이력', 'CRED', total=(True, True), ident=True)
    R('OP', '자격변경', 'CRED')
    R('ACC', '보유기기', 'REG', total=(False, True), ident=True)
    R('DEV', '식별', 'REG', total=(False, True), ident=True)
    R('ACC', '로그인', 'LA', total=(False, True))
    R('DEV', '시도기기', 'LA', total=(False, True))
    f.specialize('LA', ['LA_OK', 'LA_NO'], 'd', total=True, on='성공여부')
    R('LA_OK', '발급', 'SES', card=('1', '1'), total=(True, True))
    R('REG', '발급기기', 'SES', total=(False, True))
    f.edge('SES', 'SES_REV', subset=True)
    f.specialize('SES_REV', ['SES_LO', 'SES_TR'], 'd', total=True, on='폐기사유')
    R('LA', '원인', 'RS', total=(False, True))
    R('RR', '적용', 'RS', total=(False, True))
    R('ACC', '현재보호', 'CS_OPEN', card=('1', '1'), total=(False, True))
    R('ACC', '보호이력', 'CS_DONE', total=(False, True))
    f.specialize('CASE', ['CS_OPEN', 'CS_DONE'], 'd', total=True, on='종료일시')
    R('CASE', '근거', 'RS')
    R('CASE', '전이기록', 'CT', total=(True, True), ident=True)
    R('AT', '준수', 'CT', total=(False, True))
    R('OP', '수행', 'CT')
    R('CT', '세션폐기', 'SES_TR', total=(False, True))
    R('CASE', '자산동결', 'ITEM', card=('M', 'N'))
    R('IT', '분류', 'ITEM', total=(False, True))
    R('ACC', '보유', 'ITEM', total=(False, True))
    R('ITEM', '대상', 'TR', total=(False, True))
    R('SES', '요청', 'TR', total=(False, True))
    R('ACC', '수령', 'TR', total=(False, True))
    f.specialize('TR', ['TR_OK', 'TR_NO'], 'd', total=True, on='처리결과')
    return f


# ===================================================================== 그림 2
def identity() -> Fig:
    """신원·인증 영역"""
    f = Fig()
    E = f.entity
    E('PS', '보호상태', ref=True)
    E('ACC', '계정'); E('DEV', '기기'); E('REG', '등록기기', weak=True); E('CRED', '자격증명이력', weak=True)
    E('LA', '로그인시도'); E('LA_OK', '성공로그인'); E('LA_NO', '실패로그인')
    E('SES', '게임세션'); E('SES_REV', '폐기세션'); E('SES_LO', '로그아웃폐기세션'); E('SES_TR', '전이폐기세션')
    R = f.relate
    R('PS', '현재상태', 'ACC', total=(False, True), rid='r_state')
    R('ACC', '자격이력', 'CRED', total=(True, True), ident=True, rid='r_cred')
    R('ACC', '보유기기', 'REG', total=(False, True), ident=True, rid='r_own')
    R('DEV', '식별', 'REG', total=(False, True), ident=True, rid='r_ident')
    R('ACC', '로그인', 'LA', total=(False, True), rid='r_login')
    R('DEV', '시도기기', 'LA', total=(False, True), rid='r_trydev')
    f.specialize('LA', ['LA_OK', 'LA_NO'], 'd', total=True, on='성공여부', sid='s_LA')
    R('LA_OK', '발급', 'SES', card=('1', '1'), total=(True, True), rid='r_issue')
    R('REG', '발급기기', 'SES', total=(False, True), rid='r_issuedev')
    f.edge('SES', 'SES_REV', subset=True)
    f.specialize('SES_REV', ['SES_LO', 'SES_TR'], 'd', total=True, on='폐기사유', sid='s_REV')

    put(f, {'PS': (90, 330), 'r_state': (235, 330), 'ACC': (420, 330), 'r_login': (690, 330), 'LA': (930, 330),
            's_LA': (1095, 330), 'LA_NO': (1260, 230), 'LA_OK': (1260, 430), 'r_issue': (1260, 590),
            'SES': (1260, 760), 'SES_REV': (1470, 760), 's_REV': (1470, 650), 'SES_LO': (1385, 525),
            'SES_TR': (1580, 525), 'r_own': (420, 555), 'REG': (420, 760), 'DEV': (700, 560),
            'r_ident': (560, 660), 'r_trydev': (815, 445), 'r_issuedev': (850, 760), 'r_cred': (245, 520),
            'CRED': (120, 660)})
    acc = A(f, 'ACC', ('계정ID', 'key'), '로그인ID', '닉네임', '이메일', '비밀번호해시', '자격증명버전',
            '가입일시', ('활성세션수', 'derived'))
    f.fan('ACC', acc[:6], -165, -15, 125, 210)
    f.fan('ACC', acc[6:], 28, 62, 125)
    f.fan('DEV', A(f, 'DEV', ('기기ID', 'key'), '기기지문', '플랫폼', '최초확인일시'), -15, 70, 120, 175)
    f.fan('REG', A(f, 'REG', '신뢰여부', '신뢰일시', '최초사용일시', '최종사용일시'), 50, 150, 115, 175)
    f.fan('CRED', A(f, 'CRED', ('버전', 'partial'), '변경사유', '변경일시'), 55, 150, 105)
    f.fan('LA', A(f, 'LA', ('시도ID', 'key'), 'IP주소', '시도일시', '성공여부'), -150, -30, 110)
    f.fan('LA_NO', A(f, 'LA_NO', '실패사유'), 0, 0, 165)
    f.fan('SES', A(f, 'SES', ('세션ID', 'key'), '토큰해시', '접속IP', '발급자격증명버전', '발급일시', '만료일시',
                   ('유효여부', 'derived')), 45, 158, 125, 200)
    f.fan('SES_REV', A(f, 'SES_REV', '폐기일시', '폐기사유'), 55, 125, 105)
    return f


# ===================================================================== 그림 3
def protection() -> Fig:
    """보호 정책 영역"""
    f = Fig()
    E = f.entity
    E('ACC', '계정', ref=True); E('CRED', '자격증명이력', weak=True, ref=True)
    E('SES_TR', '전이폐기세션', ref=True); E('ITEM', '아이템', ref=True)
    E('PS', '보호상태'); E('AT', '허용전이', weak=True); E('CASE', '보호케이스')
    E('CS_OPEN', '진행중케이스'); E('CS_DONE', '종료케이스'); E('CT', '상태전이기록', weak=True); E('OP', '운영자')
    R = f.relate
    R('PS', '출발', 'AT', total=(False, True), ident=True, rid='r_from')
    R('PS', '도착', 'AT', total=(False, True), ident=True, rid='r_to')
    R('AT', '준수', 'CT', total=(False, True), rid='r_follow')
    R('CASE', '전이기록', 'CT', total=(True, True), ident=True, rid='r_rec')
    R('OP', '수행', 'CT', rid='r_perform')
    R('OP', '자격변경', 'CRED', rid='r_credchg')
    f.specialize('CASE', ['CS_OPEN', 'CS_DONE'], 'd', total=True, on='종료일시', sid='s_CASE')
    R('ACC', '현재보호', 'CS_OPEN', card=('1', '1'), total=(False, True), rid='r_cur')
    R('ACC', '보호이력', 'CS_DONE', total=(False, True), rid='r_hist')
    R('CT', '세션폐기', 'SES_TR', total=(False, True), rid='r_revoke')
    R('CASE', '자산동결', 'ITEM', card=('M', 'N'), rid='r_freeze')

    put(f, {'SES_TR': (1000, 60), 'r_revoke': (1000, 180), 'PS': (150, 320), 'r_from': (380, 235),
            'r_to': (380, 405), 'AT': (600, 320), 'r_follow': (800, 320), 'CT': (1000, 320),
            'r_perform': (1215, 320), 'OP': (1420, 320), 'r_credchg': (1420, 480), 'CRED': (1420, 630),
            'r_rec': (1000, 480), 'CASE': (1000, 640), 'r_freeze': (770, 640), 'ITEM': (545, 640),
            's_CASE': (1000, 760), 'CS_OPEN': (860, 860), 'CS_DONE': (1140, 860), 'r_cur': (900, 965),
            'r_hist': (1100, 965), 'ACC': (1000, 1065)})
    f.fan('PS', A(f, 'PS', ('상태코드', 'key'), '상태명', '로그인허용', '이동허용', '케이스종료', '표시순서'),
          110, 250, 120, 185)
    f.fan('AT', A(f, 'AT', '세션폐기여부', '자격회전여부', '자산동결여부', '설명'), -118, -18, 110, 165)
    f.fan('CT', A(f, 'CT', ('순번', 'partial'), '사유', '전이일시'), -158, -110, 140)
    f.fan('OP', A(f, 'OP', ('운영자ID', 'key'), '사용자명', '표시이름', '활성여부'), -110, 15, 120, 170)
    f.fan('CASE', A(f, 'CASE', ('케이스ID', 'key'), '개시일시'), -28, 28, 130)
    f.fan('CS_DONE', A(f, 'CS_DONE', '종료일시'), 0, 0, 170)
    f.fan('r_freeze', A(f, 'r_freeze', '동결일시'), -90, -90, 85)
    return f


# ===================================================================== 그림 4
def detection_assets() -> Fig:
    """탐지·자산 영역"""
    f = Fig()
    E = f.entity
    E('LA', '로그인시도', ref=True); E('CASE', '보호케이스', ref=True)
    E('ACC', '계정', ref=True); E('SES', '게임세션', ref=True)
    E('RR', '탐지규칙'); E('RS', '위험신호'); E('IT', '아이템종류'); E('ITEM', '아이템')
    E('TR', '아이템이동'); E('TR_OK', '승인이동'); E('TR_NO', '거절이동')
    R = f.relate
    R('LA', '원인', 'RS', total=(False, True), rid='r_cause')
    R('RR', '적용', 'RS', total=(False, True), rid='r_rule')
    R('CASE', '근거', 'RS', rid='r_basis')
    R('IT', '분류', 'ITEM', total=(False, True), rid='r_kind')
    R('ACC', '보유', 'ITEM', total=(False, True), rid='r_own')
    R('ITEM', '대상', 'TR', total=(False, True), rid='r_target')
    R('SES', '요청', 'TR', total=(False, True), rid='r_req')
    R('ACC', '수령', 'TR', total=(False, True), rid='r_recv')
    f.specialize('TR', ['TR_OK', 'TR_NO'], 'd', total=True, on='처리결과', sid='s_TR')

    put(f, {'LA': (150, 200), 'r_cause': (390, 200), 'RS': (640, 200), 'r_rule': (880, 200), 'RR': (1120, 200),
            'r_basis': (640, 345), 'CASE': (640, 480), 'SES': (900, 470), 'r_req': (900, 590),
            'IT': (170, 730), 'r_kind': (340, 730), 'ITEM': (500, 730), 'r_target': (700, 730), 'TR': (900, 730),
            's_TR': (1085, 730), 'TR_OK': (1245, 655), 'TR_NO': (1245, 805), 'r_own': (580, 880),
            'r_recv': (820, 880), 'ACC': (700, 1010)})
    f.fan('RS', A(f, 'RS', ('신호ID', 'key'), '탐지일시', '탐지근거'), -145, -35, 105)
    f.fan('RR', A(f, 'RR', ('규칙코드', 'key'), '규칙명', '기간(분)', '임계치', '심각도', '사용여부'),
          -80, 80, 130, 190)
    f.fan('IT', A(f, 'IT', ('종류ID', 'key'), '종류명', '등급', '거래가능'), 100, 260, 115, 170)
    f.fan('ITEM', A(f, 'ITEM', ('아이템ID', 'key'), '획득일시'), -125, -70, 110)
    f.fan('TR', A(f, 'TR', ('이동ID', 'key'), '요청일시', '판정일시', '처리결과'), 25, 85, 125, 185)
    f.fan('TR_NO', A(f, 'TR_NO', '거절사유'), 0, 0, 165)
    return f



# ===================================================================== 범례
def legend() -> Fig:
    f = Fig()
    x, items = 60, [
        ('e', f.entity('L1', '개체'), '강한 개체'), ('w', f.entity('L2', '약한개체', weak=True), '약한 개체'),
        ('r', f.rel('L3', '관계'), '관계'), ('i', f.rel('L4', '식별관계', ident=True), '식별 관계'),
        ('a', f.attr('L5', '속성'), '속성'), ('k', f.attr('L6', '키속성', key=True), '키 속성'),
        ('p', f.attr('L7', '부분키', partial=True), '부분키(약한 개체)'),
        ('d', f.attr('L8', '유도속성', derived=True), '유도 속성'), ('f', f.entity('L9', '참조', ref=True), '다른 그림의 개체'),
    ]
    for _, nid, cap in items:
        w = max(f.nodes[nid]['w'], 96)
        f.place(nid, x + w / 2, 40)
        f.place(f.text(nid + 'c', cap, 11), x + w / 2, 82)
        x += w + 38
    # 참여·카디널리티
    f.entity('P1', 'A'); f.rel('P2', '관계'); f.entity('P3', 'B')
    f.edge('P1', 'P2', card='1', card_at='b'); f.edge('P2', 'P3', total=True, card='N', card_at='a')
    f.place('P1', 90, 150); f.place('P2', 240, 150); f.place('P3', 390, 150)
    f.place(f.text('Pc', 'A 1 : N B — 단선 = 부분 참여(A는 관계 없어도 됨), 이중선 = 전체 참여(B는 반드시 참여)', 11), 400, 196)
    # 특수화
    f.entity('S0', '상위개체'); f.spec('S1', 'd'); f.entity('S2', '하위1'); f.entity('S3', '하위2')
    f.edge('S0', 'S1', total=True, label='정의속성'); f.edge('S1', 'S2', subset=True); f.edge('S1', 'S3', subset=True)
    f.place('S0', 860, 150); f.place('S1', 1010, 150); f.place('S2', 1150, 120); f.place('S3', 1150, 180)
    f.place(f.text('Sc', 'd = 분리(배타) 특수화, 이중선 = 전체 특수화, ⊃ 기호 = 하위 개체 쪽', 11), 1030, 222)
    return f

FIGURES = {
    'eer_legend': legend,
    'eer_overview': overview,
    'eer_identity': identity,
    'eer_protection': protection,
    'eer_detection_assets': detection_assets,
}

if __name__ == '__main__':
    for name in sys.argv[1:] or list(FIGURES):
        fig = FIGURES[name]()
        fig.layout() if name == 'eer_overview' else fig.layout_manual()
        path = render_png(fig.svg(), name)
        print(f'{name}: {fig.W:.0f}x{fig.H:.0f} -> {path.name}')
