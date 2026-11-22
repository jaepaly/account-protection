// 설계 산출물(요구사항 명세서 · 업무 규칙/도메인 · 개념 EER) → .docx
//   node build_spec.js <출력 경로>
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Header, Footer,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, VerticalAlign, PageOrientation,
  PageNumber, PageBreak, LevelFormat, TableLayoutType,
} = require('docx');
const C = { ...require('./content'), ...require('./content_review') };

const FONT = 'Malgun Gothic';
const IMG = path.join(__dirname, 'img');
const PORTRAIT_W = 11906 - 2 * 1134;          // A4, 여백 20mm → 본문 폭 9638 DXA
const PAGE = { width: 11906, height: 16838 };

// ---------------------------------------------------------------- 기본 요소
const run = (text, o = {}) => new TextRun({ text, font: FONT, size: o.size || 20, bold: o.bold, italics: o.italics, color: o.color });
const para = (text, o = {}) => new Paragraph({
  children: Array.isArray(text) ? text : [run(text, o)],
  alignment: o.align, spacing: { before: o.before || 0, after: o.after ?? 100, line: o.line || 300 },
  numbering: o.bullet ? { reference: 'bullets', level: 0 } : undefined,
  keepNext: o.keepNext,
});
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(text, { size: 30, bold: true })], spacing: { before: 280, after: 160 }, keepNext: true });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [run(text, { size: 24, bold: true })], spacing: { before: 240, after: 100 }, keepNext: true });
const h3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [run(text, { size: 21, bold: true, color: '1F3864' })], spacing: { before: 160, after: 80 }, keepNext: true });
const caption = (text) => para(text, { size: 18, align: AlignmentType.CENTER, after: 160, color: '333333' });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

const border = { style: BorderStyle.SINGLE, size: 4, color: '8C8C8C' };
const BORDERS = { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border };

function cell(text, width, o = {}) {
  const lines = String(text).split('\n');
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    verticalAlign: VerticalAlign.CENTER,
    children: lines.map((line) => new Paragraph({
      children: [run(line, { size: o.size || 17, bold: o.bold })],
      alignment: o.center ? AlignmentType.CENTER : AlignmentType.LEFT,
      spacing: { after: 0, line: 260 },
    })),
  });
}

function table(headers, rows, widths, o = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const center = new Set(o.center || []);
  const out = [];
  if (headers) {
    out.push(new TableRow({ tableHeader: true, cantSplit: true,
      children: headers.map((h, i) => cell(h, widths[i], { bold: true, fill: 'DCE6F2', center: true })) }));
  }
  rows.forEach((r) => out.push(new TableRow({ cantSplit: true,
    children: r.map((c, i) => cell(c, widths[i], {
      bold: o.boldFirst && i === 0, fill: o.shadeFirst && i === 0 ? 'F2F2F2' : undefined, center: center.has(i),
    })) })));
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, borders: BORDERS, rows: out,
                    layout: TableLayoutType.FIXED });   // 긴 문자열이 있어도 열 너비를 넘지 않게
}

function image(name, maxW, maxH) {
  const buf = fs.readFileSync(path.join(IMG, `${name}.png`));
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  const scale = Math.min(maxW / w, maxH / h);
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 60 }, keepNext: true,
    children: [new ImageRun({ type: 'png', data: buf, transformation: { width: Math.round(w * scale), height: Math.round(h * scale) } })],
  });
}

const gap = () => para('', { after: 60 });

// ---------------------------------------------------------------- 표지 블록
const cover = [
  para(C.meta.course, { size: 18, color: '555555', after: 40 }),
  para(C.meta.title, { size: 36, bold: true, after: 60 }),
  para(C.meta.subtitle, { size: 22, color: '1F3864', after: 160 }),
  table(null, [['작성자', C.meta.author, '작성일', C.meta.date, '버전', C.meta.version]],
        [1000, 2600, 1000, 2000, 900, 2138], { shadeFirst: false }),
  gap(),
  para('문서 구성', { bold: true, size: 20, after: 60 }),
  para('1장 요구사항 명세서 — 개요, 제안서 피드백 반영, 사용자 그룹·요구 충돌, 운영 환경·DB 선택 근거, 기능 요구사항(REQ)과 핵심 기능 상세, 비기능 요구사항(NFR)', { bullet: true, after: 40 }),
  para('2장 업무 규칙·도메인 — 업무 규칙(BR)과 보장 위치, 도메인 사전, 엔티티 사전, 관계 명세(참여 최소·최대)', { bullet: true, after: 40 }),
  para('3장 개념 EER — 표기법, 전체 EER과 영역별 상세 EER(속성 포함), 상속(특수화)·약한 엔티티 명세, 가이드라인 평가 항목 대응과 핵심 엔티티 명세표', { bullet: true, after: 160 }),
];

// ---------------------------------------------------------------- 1장
const ch1 = [
  h1('1. 요구사항 명세서'),
  h2('1.1 목적과 범위'),
  ...C.purpose.map((t) => para(t)),
  table(['항목', '내용'], C.projectTable, [1700, PORTRAIT_W - 1700], { boldFirst: true, shadeFirst: true }),
  h2('1.2 제안서 피드백 반영'),
  table(['교수님 피드백', '반영 내용', '위치'], C.feedback, [2600, 5338, 1700], { boldFirst: true }),
  h3('제안서 기능 7개의 처리'),
  table(['제안서 기능', 'v1.0 처리', '요구사항'], C.featureMap, [3300, 4138, 2200], { boldFirst: true }),
  h2('1.3 사용자 그룹과 업무'),
  table(['사용자 그룹', '수행 업무', 'DB 역할'], C.userGroups, [1900, 6238, 1500], { boldFirst: true, center: [2] }),
  h3('요구 충돌과 해결 정책'),
  para('사용자 그룹마다 요구가 부딪히는 지점을 정리하고, 정책을 코드가 아닌 데이터·권한으로 설정 가능하게 해서 해결했다.'),
  table(['충돌', '내용', '해결 정책'], C.conflicts, [1900, 3869, 3869], { boldFirst: true }),
  h2('1.4 운영 환경과 DB 선택 근거'),
  table(['항목', '내용'], C.environment, [1700, PORTRAIT_W - 1700], { boldFirst: true, shadeFirst: true }),
  h3('DB 선택 근거'),
  para('DB 종류보다 「왜 이 DB인가」의 기술적 타당성이 중요하다는 가이드라인에 따라, 이 설계가 실제로 의존하는 기능과 업무 규칙(BR)으로 근거를 적었다.'),
  table(['비교', '판단 근거'], C.dbChoice, [2000, PORTRAIT_W - 2000], { boldFirst: true, shadeFirst: true }),
  h2('1.5 기능 요구사항'),
  para('REQ-E로 시작하는 항목은 다음 버전의 확장 요구사항이다.'),
  table(['ID', '사용자', '요구사항', '관련 데이터', '중요도', '상태'], C.functional, [900, 950, 4300, 2088, 600, 800],
        { boldFirst: true, center: [1, 4, 5] }),
  h2('1.6 핵심 기능 상세'),
  ...C.details.flatMap(([title, rows]) => [
    h3(title),
    table(null, rows, [1300, PORTRAIT_W - 1300], { boldFirst: true, shadeFirst: true }),
  ]),
  h2('1.7 비기능 요구사항'),
  table(['ID', '요구사항 / 측정 조건', '검증 계획', '상태'], C.nonFunctional, [850, 4400, 3088, 1300],
        { boldFirst: true, center: [3] }),
];

// ---------------------------------------------------------------- 2장
const ch2 = [
  h1('2. 업무 규칙 · 도메인'),
  h2('2.1 업무 규칙'),
  para('각 규칙이 DB의 어디에서 보장되는지(제약·트리거·함수·권한)와 그 한계를 함께 적었다.'),
  table(['ID', '관련 요구사항', '업무 규칙', '보장 위치 · 주의점'], C.businessRules, [750, 1050, 3700, 4138],
        { boldFirst: true, center: [1] }),
  h2('2.2 도메인 사전'),
  table(['도메인', '물리 타입', '값 / 제약', '예시', '의미 / 사용 규칙'], C.domains, [1750, 1450, 2250, 1850, 2338],
        { boldFirst: true }),
  h2('2.3 엔티티 사전'),
  para('분류는 강의 기준(유형·무형·이력·코드 개체)과 강한·약한 엔티티 구분을 함께 표기했다. 숫자로 적은 예상 행 수는 1단계 합성 데이터의 실제 적재 건수이고, 운영 중에 생기는 케이스·전이 기록은 예상치다.'),
  table(['엔티티(물리명)', '의미', '분류', '식별자', '대체키', '예상 행 수'], C.entities, [1750, 2500, 1150, 1500, 1500, 1238],
        { boldFirst: true, center: [2] }),
  h2('2.4 관계 명세 — 관계를 문장으로 검증'),
  para('⇒ 는 식별 관계(약한 엔티티), → 는 1:N, — 는 1:1, ↔ 는 M:N을 뜻한다.'),
  table(['관계', '양쪽 (최소 · 최대) 참여', '설계 의미'], C.relationships, [2900, 3300, 3438], { boldFirst: true }),
];

// ---------------------------------------------------------------- 3장 (세로 앞부분)
const ch3a = [
  h1('3. 개념 EER'),
  h2('3.1 표기법'),
  para('강의자료(3. Data Modeling)의 Peter Chen 표기에 EER의 특수화(상속) 표기를 더했다. 그림 2~4에서 점선·회색 사각형은 다른 그림에서 속성까지 정의한 개체를 참조로 다시 그린 것이다.'),
  image('eer_legend', 640, 160),
  caption('표기법 범례'),
  para('다이어그램은 실제 구현 스키마와 대응한다. 개체 16개와 M:N 관계 「자산동결」이 테이블 17개가 되고, 하위 개체는 상위 테이블의 판별 컬럼과 CHECK 제약이 된다. 자격증명버전·발급자격증명버전은 속성으로 그렸으며, 그 값이 자격증명이력에 있어야 한다는 규칙은 복합 FK(BR-11·12)로 보장한다. 모든 개체·관계는 그림 1에 한 번에 나타나고, 속성은 영역별로 나눈 그림 2(신원·인증), 그림 3(보호 정책), 그림 4(탐지·자산)에 표시했다. 각 관계는 그림 2~4 중 정확히 한 곳에 속성과 함께 그려져 있다.'),
];

// ---------------------------------------------------------------- 3장 (가로: 그림)
const LW = 1000, LH = 600;   // 가로 A4(여백 15mm) 본문에 맞춘 그림 최대 크기(px)
const ch3fig = [
  h2('3.2 전체 EER 다이어그램'),
  image('eer_overview', LW, LH),
  caption('그림 1. 전체 EER — 개체 16, 하위 개체 9, 관계 26, 특수화 5 (속성은 그림 2~4)'),
  pageBreak(),
  h2('3.3 영역별 상세 EER'),
  image('eer_identity', LW, LH - 40),
  caption('그림 2. 신원·인증 영역 — 계정, 기기, 등록기기, 자격증명이력, 로그인시도(성공/실패), 게임세션(폐기 → 로그아웃/전이)'),
  pageBreak(),
  image('eer_protection', LW, LH),
  caption('그림 3. 보호 정책 영역 — 보호상태, 허용전이, 보호케이스(진행중/종료), 상태전이기록, 운영자'),
  pageBreak(),
  image('eer_detection_assets', LW, LH),
  caption('그림 4. 탐지·자산 영역 — 탐지규칙, 위험신호, 아이템종류, 아이템, 아이템이동(승인/거절)'),
];

// ---------------------------------------------------------------- 3장 (세로 뒷부분)
const ch3b = [
  h2('3.4 상속(특수화) 명세'),
  para('하위 개체는 고유 속성이 0~2개뿐이고 대부분 따로 참조되지 않는다. 그래서 논리 설계에서는 하위 개체마다 테이블을 두지 않고 상위 테이블 하나에 판별 컬럼과 CHECK 제약을 두어 분리·전체 조건을 직접 강제할 예정이다. 하위 개체별 테이블로 나누면 조회마다 1:1 조인이 생기고, 「정확히 하나의 하위에만 속함」을 테이블 간 제약으로 따로 보장해야 한다.'),
  table(['상위 → 하위', '제약', '정의 속성', '하위 고유 속성 · 관계', '적용 근거', '논리 매핑(예정)'], C.specializations,
        [1750, 1000, 1000, 1900, 2000, 1988], { boldFirst: true, center: [1, 2] }),
  h2('3.5 약한 엔티티 명세'),
  table(['약한 엔티티', '소유 엔티티', '부분키', '식별 관계', '적용 근거'], C.weakEntities, [1300, 1600, 1500, 1300, 3938],
        { boldFirst: true, center: [2, 3] }),
  h2('3.6 가이드라인 평가 항목 대응'),
  para('프로젝트 가이드라인의 평가 항목별로 이 설계가 무엇으로 대응하는지와 근거 위치를 정리했다. 다음 단계(논리·물리 설계, 구현)에서 채울 부분은 그렇게 표시했다.'),
  table(['평가 항목', '가이드라인 요구', '이 설계의 대응', '근거 위치'], C.guidelineMap, [1600, 2000, 4438, 1600], { boldFirst: true }),
  h3('핵심 엔티티 명세표 (데이터 모델 복잡도)'),
  table(['엔티티', '핵심 속성', 'PK', 'FK', 'UK', '예상 행 수'], C.coreEntities, [1150, 2050, 1400, 3138, 1200, 700], { boldFirst: true }),
  h3('데이터 모델 복잡도 요약'),
  table(['기준', '이 설계'], C.complexity, [2000, PORTRAIT_W - 2000], { boldFirst: true, shadeFirst: true }),
];

// ---------------------------------------------------------------- 문서
const header = new Header({ children: [para(`${C.meta.title} — 설계 산출물`, { size: 16, color: '808080', align: AlignmentType.RIGHT, after: 0 })] });
const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
  children: [new TextRun({ children: ['- ', PageNumber.CURRENT, ' -'], font: FONT, size: 16, color: '808080' })] })] });
const portrait = (children) => ({
  properties: { page: { size: PAGE, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134, header: 567, footer: 567 } } },
  headers: { default: header }, footers: { default: footer }, children,
});
const landscape = (children) => ({
  properties: { page: { size: { ...PAGE, orientation: PageOrientation.LANDSCAPE },
                        margin: { top: 850, bottom: 850, left: 850, right: 850, header: 425, footer: 425 } } },
  headers: { default: header }, footers: { default: footer }, children,
});

const doc = new Document({
  creator: C.meta.author, title: `${C.meta.title} — 설계 산출물`,
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 30, bold: true }, paragraph: { outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 24, bold: true }, paragraph: { outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 21, bold: true }, paragraph: { outlineLevel: 2 } },
    ],
  },
  numbering: { config: [{ reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [portrait([...cover, ...ch1, pageBreak(), ...ch2, ...ch3a]), landscape(ch3fig), portrait(ch3b)],
});

const out = process.argv[2] || path.join(__dirname, 'spec.docx');
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log(`wrote ${out} (${buf.length} bytes)`); });
