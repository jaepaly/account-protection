// 제출본: 과제가 요구한 항목만 — ① 요구사항 명세서(기능·비기능) ② 업무 규칙·도메인 사전·엔티티 사전 ③ 개념 EER
//   node build_submit.js <출력 경로>
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

// ---------------------------------------------------------------- 표지
const cover = [
  para(C.meta.course, { size: 18, color: '555555', after: 40 }),
  para(C.meta.title, { size: 36, bold: true, after: 60 }),
  para('요구사항 명세서 · 업무 규칙/도메인 · 개념 EER', { size: 22, color: '1F3864', after: 160 }),
  table(null, [['작성자', C.meta.author, '작성일', '2026-11-05', '버전', 'v1.2']],
        [1000, 2600, 1000, 2000, 900, 2138]),
  gap(),
];

// ---------------------------------------------------------------- 1. 요구사항 명세서 (기능 + 비기능)
const ch1 = [
  h1('1. 요구사항 명세서'),
  h2('1.1 기능 요구사항'),
  para('REQ-E로 시작하는 항목은 이번 범위에서 제외하고 다음 버전으로 미룬 확장 요구사항이다.'),
  table(['ID', '사용자', '요구사항', '관련 데이터'], C.functional.map((r) => [r[0], r[1], r[2], r[3]]),
        [900, 1000, 5200, 2538], { boldFirst: true, center: [1] }),
  h2('1.2 핵심 기능 상세'),
  ...C.details.flatMap(([title, rows]) => [
    h3(title),
    table(null, rows, [1300, PORTRAIT_W - 1300], { boldFirst: true, shadeFirst: true }),
  ]),
  h2('1.3 비기능 요구사항'),
  table(['ID', '요구사항 / 측정 조건', '검증 계획'], C.nonFunctional.map((r) => [r[0], r[1], r[2]]),
        [900, 5300, 3438], { boldFirst: true }),
];

// ---------------------------------------------------------------- 2. 업무 규칙 · 도메인
const ch2 = [
  h1('2. 업무 규칙 · 도메인'),
  h2('2.1 업무 규칙'),
  table(['ID', '관련 요구사항', '업무 규칙', '보장 위치 · 주의점'], C.businessRules, [750, 1050, 3700, 4138],
        { boldFirst: true, center: [1] }),
  h2('2.2 도메인 사전'),
  table(['도메인', '물리 타입', '값 / 제약', '예시', '의미 / 사용 규칙'], C.domains, [1750, 1450, 2250, 1850, 2338],
        { boldFirst: true }),
  h2('2.3 엔티티 사전'),
  table(['엔티티(물리명)', '의미', '식별자', '대체키', '예상 행 수'],
        C.entities.map((r) => [r[0], r[2].includes('약') ? `${r[1]} (약한 엔티티)` : r[1], r[3], r[4], r[5]]),
        [1900, 3500, 1600, 1500, 1138], { boldFirst: true }),
  h3('관계 — 문장으로 검증'),
  para('⇒ 식별 관계(약한 엔티티), → 1:N, — 1:1, ↔ M:N'),
  table(['관계', '양쪽 (최소 · 최대) 참여', '설계 의미'], C.relationships, [2900, 3300, 3438], { boldFirst: true }),
];

// ---------------------------------------------------------------- 3. 개념 EER
const ch3a = [
  h1('3. 개념 EER'),
  image('eer_legend', 640, 160),
  caption('표기법 — Chen 표기(강의자료 3. Data Modeling) + EER 특수화. 그림 2~4의 점선·회색 사각형은 다른 그림에서 속성까지 정의한 개체'),
];
const LW = 1000, LH = 600;
const ch3fig = [
  image('eer_overview', LW, LH),
  caption('그림 1. 전체 EER — 개체 16, 하위 개체 9, 관계 26, 특수화 5 (속성은 그림 2~4)'),
  pageBreak(),
  image('eer_identity', LW, LH - 40),
  caption('그림 2. 신원·인증 영역 — 계정, 기기, 등록기기, 자격증명이력, 로그인시도(성공/실패), 게임세션(폐기 → 로그아웃/전이)'),
  pageBreak(),
  image('eer_protection', LW, LH),
  caption('그림 3. 보호 정책 영역 — 보호상태, 허용전이, 보호케이스(진행중/종료), 상태전이기록, 운영자'),
  pageBreak(),
  image('eer_detection_assets', LW, LH),
  caption('그림 4. 탐지·자산 영역 — 탐지규칙, 위험신호, 아이템종류, 아이템, 아이템이동(승인/거절)'),
];

// ---------------------------------------------------------------- 문서
const header = new Header({ children: [para(`${C.meta.title}`, { size: 16, color: '808080', align: AlignmentType.RIGHT, after: 0 })] });
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
  creator: C.meta.author, title: C.meta.title,
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 30, bold: true }, paragraph: { outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 24, bold: true }, paragraph: { outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 21, bold: true }, paragraph: { outlineLevel: 2 } },
    ],
  },
  numbering: { config: [{ reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [portrait([...cover, ...ch1, pageBreak(), ...ch2, ...ch3a]), landscape(ch3fig)],
});

const out = process.argv[2] || path.join(__dirname, 'submit.docx');
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log(`wrote ${out} (${buf.length} bytes)`); });
