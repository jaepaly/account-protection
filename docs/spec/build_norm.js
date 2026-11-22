// 정규화 제출본: ① 정규화 진행 과정 ② 정규화를 적용한 테이블
//   node build_norm.js <출력 경로>
// 최종 테이블(2장)은 실제 DB 카탈로그(norm_catalog.json, scripts/export_catalog_json.py)에서 만든다.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, Header, Footer,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, VerticalAlign,
  PageNumber, LevelFormat, TableLayoutType, UnderlineType, PageBreak,
} = require('docx');
const C = require('./content_norm');
const CAT = JSON.parse(fs.readFileSync(path.join(__dirname, 'norm_catalog.json'), 'utf-8'));

const FONT = 'Malgun Gothic';
const W = 11906 - 2 * 1134;                   // A4, 여백 20mm → 본문 폭 9638 DXA
const PAGE = { width: 11906, height: 16838 };

// ---------------------------------------------------------------- 기본 요소
const run = (text, o = {}) => new TextRun({
  text, font: FONT, size: o.size || 20, bold: o.bold, italics: o.italics, color: o.color,
  underline: o.underline ? { type: UnderlineType.SINGLE } : undefined,
});

// "#속성" = 기본키(밑줄), "@속성" = 외래키(기울임), "#@속성" = 둘 다. 이메일의 @ 는 앞에 글자가 있어 건드리지 않는다.
const MARK = /(^|[\s(,+{[])(#@|#|@)([^,()\s\]}]+)/g;
function marked(text, o = {}) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(MARK)) {
    const start = m.index + m[1].length;
    if (start > last) out.push(run(text.slice(last, start), o));
    out.push(run(m[3], { ...o, underline: m[2].includes('#'), italics: m[2].includes('@') }));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(run(text.slice(last), o));
  return out;
}

const para = (text, o = {}) => new Paragraph({
  children: Array.isArray(text) ? text : marked(text, o),
  alignment: o.align, spacing: { before: o.before || 0, after: o.after ?? 100, line: o.line || 300 },
  numbering: o.bullet ? { reference: 'bullets', level: 0 } : undefined,
  indent: o.indent ? { left: o.indent } : undefined,
  keepNext: o.keepNext,
});
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(text, { size: 30, bold: true })], spacing: { before: 280, after: 160 }, keepNext: true });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [run(text, { size: 24, bold: true })], spacing: { before: 240, after: 100 }, keepNext: true });
const h3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [run(text, { size: 21, bold: true, color: '1F3864' })], spacing: { before: 160, after: 80 }, keepNext: true });
const label = (text) => para(text, { size: 18, bold: true, color: '1F3864', after: 60, keepNext: true });
const gap = () => para('', { after: 60 });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

const border = { style: BorderStyle.SINGLE, size: 4, color: '8C8C8C' };
const BORDERS = { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border };

function cell(content, width, o = {}) {
  const lines = Array.isArray(content) ? [content] : String(content).split('\n');
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    margins: { top: 45, bottom: 45, left: 80, right: 80 },
    verticalAlign: VerticalAlign.CENTER,
    children: lines.map((line) => new Paragraph({
      children: Array.isArray(line) ? line : marked(line, { size: o.size || 17, bold: o.bold }),
      alignment: o.center ? AlignmentType.CENTER : AlignmentType.LEFT,
      spacing: { after: 0, line: 250 },
    })),
  });
}

function table(headers, rows, widths, o = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  if (total !== W) throw new Error(`table width ${total} != ${W}: ${headers}`);
  const center = new Set(o.center || []);
  const out = [];
  if (headers) {
    out.push(new TableRow({ tableHeader: true, cantSplit: true,
      children: headers.map((h, i) => cell(h, widths[i], { bold: true, fill: 'DCE6F2', center: true, size: o.size })) }));
  }
  rows.forEach((r) => out.push(new TableRow({ cantSplit: true,
    children: r.map((c, i) => cell(c, widths[i], {
      bold: o.boldFirst && i === 0, fill: o.shadeFirst && i === 0 ? 'F2F2F2' : undefined, center: center.has(i), size: o.size,
    })) })));
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, borders: BORDERS, rows: out,
                    layout: TableLayoutType.FIXED });
}

// 좁은 칸에서 이메일이 @ 뒤에서 줄바꿈되도록
const breakable = (rows) => rows.map((r) => r.map((c) => String(c).replace(/@example/g, '@​example')));
const form = (f) => [label(f.title), para(f.unf, { size: 17, after: 80, keepNext: true }),
                      table(f.headers, breakable(f.rows), f.widths, { size: 15 }), gap()];
// "table.column" → 테이블명과 컬럼명을 두 줄로 (좁은 칸에서 단어 중간이 끊기지 않게)
const splitCol = (rows) => rows.map(([c, ...rest]) => [c.replace('.', '.\n'), ...rest]);
// 표 바로 앞 설명 문단은 표와 같은 쪽에
const lead = (text) => para(text, { keepNext: true });
// 단계별 결과 릴레이션 목록
const relList = (rels) => rels.map((t) => para(t, { size: 18, bullet: true, after: 40 }));

// ---------------------------------------------------------------- 표지
const cover = [
  para(C.meta.course, { size: 18, color: '555555', after: 40 }),
  para(C.meta.title, { size: 36, bold: true, after: 60 }),
  para(C.meta.subtitle, { size: 22, color: '1F3864', after: 160 }),
  table(null, [['작성자', C.meta.author, '작성일', C.meta.date, '버전', C.meta.version]],
        [1000, 2600, 1000, 2000, 900, 2138]),
  gap(),
];

// ---------------------------------------------------------------- 1. 정규화 진행 과정
const ch1 = [
  h1('1. 정규화 진행 과정'),
  h2('1.1 출발점 — 비정규 양식과 함수 종속'),
  ...C.startIntro.map((t) => para(t)),
  ...form(C.formAccount),
  ...form(C.formCase),
  ...form(C.formLogLogin),
  ...form(C.formLogTransfer),
  label('양식에서 찾은 함수 종속 (X → Y : X 값이 같으면 Y 값도 같다)'),
  table(['ID', '함수 종속', '근거'], C.fds, [800, 5100, 3738], { boldFirst: true, center: [0] }),

  h2('1.2 제1정규형 (1NF) — 반복 그룹과 복합값 제거'),
  lead(C.nf1Intro),
  table(['위반 유형', '위치', '처리'], C.nf1, [1000, 3300, 5338], { boldFirst: true, center: [0] }),
  para(C.nf1Keys, { before: 100 }),
  label(C.nf1Example.caption),
  table(C.nf1Example.headers, C.nf1Example.rows, C.nf1Example.widths, { size: 16, center: [1, 2, 3, 4, 7, 8, 9, 10] }),
  gap(),
  label('1NF 결과'),
  ...relList(C.nf1Result),
  para(C.nf1Note, { before: 80 }),

  h2('1.3 제2정규형 (2NF) — 부분 함수 종속 제거'),
  lead(C.nf2Intro),
  table(['릴레이션 (기본키)', '부분 함수 종속', '이상 현상', '분해 결과'], C.nf2, [1600, 2100, 2900, 3038], { boldFirst: true }),
  gap(),
  label('2NF 결과 (바뀐 릴레이션)'),
  ...relList(C.nf2Result),
  para(C.nf2Rest, { before: 60 }),

  h2('1.4 제3정규형 (3NF) — 이행 함수 종속 제거'),
  lead(C.nf3Intro),
  table(['릴레이션', '이행 함수 종속', '이상 현상', '분해 결과'], C.nf3, [1100, 2500, 2700, 3338], { boldFirst: true }),
  gap(),
  label('3NF 결과 — 정규화를 마친 릴레이션 18개'),
  ...relList(C.nf3Result),
  gap(),
  ...C.nf3Notes.map((t) => para(t, { bullet: true, after: 60 })),

  h2('1.5 BCNF 검사와 구현에서 둔 유도 값'),
  lead(C.bcnfIntro),
  table(['테이블', '후보키'], C.candidateKeys, [2200, 7438], { boldFirst: true }),
  gap(),
  label('(1) 유도 속성 — DBMS가 계산하는 생성 컬럼'),
  lead(C.derivedIntro),
  table(['컬럼', '계산식', '쓰는 곳'], splitCol(C.derived), [1900, 3900, 3838], { boldFirst: true }),
  gap(),
  label('(2) 다른 테이블에서 유도할 수 있는 값 — 테이블 자체는 BCNF'),
  lead(C.exceptionsIntro),
  table(['컬럼', '유도 관계', '남긴 이유', '일치 보장'], splitCol(C.exceptionsAcross), [1700, 2300, 3000, 2638], { boldFirst: true }),

  h2('1.6 이상 현상 제거 결과'),
  table(['이상 현상', '정규화 전 (양식)', '정규화 후'], C.anomalies, [1100, 4800, 3738], { boldFirst: true, center: [0] }),
];

// ---------------------------------------------------------------- 2. 정규화 적용한 테이블
const names = Object.fromEntries(C.finalTables.map((r) => [r[0], r]));
const fkCols = (t) => new Set(CAT[t].fks.flatMap((f) => f.cols));
const tuple = (cols) => (cols.length > 1 ? `(${cols.join(', ')})` : cols[0]);

function schemaLine(t) {
  const pk = new Set(CAT[t].pk), fk = fkCols(t);
  const kids = [run(`${names[t][1]}  `, { size: 18, color: '555555' }), run(t, { size: 18, bold: true }), run('(', { size: 18 })];
  CAT[t].columns.forEach((c, i) => {
    if (i) kids.push(run(', ', { size: 18 }));
    kids.push(run(c.name, { size: 18, underline: pk.has(c.name), italics: fk.has(c.name),
                            color: c.generated ? '8C8C8C' : undefined }));   // 회색 = 생성 컬럼
  });
  kids.push(run(')', { size: 18 }));
  return para(kids, { after: 70, line: 280 });
}

function summaryRow(t) {
  const v = CAT[t], pk = new Set(v.pk);
  const fks = v.fks.map((f) => `${tuple(f.cols)} → ${f.ref}`).join('\n') || '—';
  const uks = [
    ...v.uniques.filter((u) => !v.pk.every((k) => u.includes(k))).map(tuple),
    ...v.uniques.filter((u) => v.pk.every((k) => u.includes(k))).map((u) => `${tuple(u)} — 복합 FK 참조용`),
    ...v.partial_uniques.map((p) => p.replace(/^\((.*)\) WHERE \((.*)\)$/, '$1 ($2인 행)')),
  ].join('\n') || '—';
  return [`${t}\n${names[t][1]}`, tuple(v.pk), fks, uks, names[t][2], names[t][3]];
}

const missing = Object.keys(CAT).filter((t) => !names[t]);
if (missing.length) throw new Error(`no Korean name for ${missing}`);

const ch2 = [
  pageBreak(),
  h1('2. 정규화를 적용한 테이블'),
  para(C.finalIntro),
  h2('2.1 관계 스키마'),
  para([run('표기: ', { size: 18 }), run('밑줄', { size: 18, underline: true }), run(' = 기본키, ', { size: 18 }),
        run('기울임', { size: 18, italics: true }), run(' = 외래키, ', { size: 18 }),
        run('회색', { size: 18, color: '8C8C8C' }), run(' = DBMS가 계산하는 생성 컬럼', { size: 18 })], { after: 100, keepNext: true }),
  ...C.finalTables.map(([t]) => schemaLine(t)),
  h2('2.2 테이블별 키와 정규형'),
  table(['테이블', '기본키', '외래키 → 참조 테이블', 'UNIQUE 제약', '정규형', '도출 단계'],
        C.finalTables.map(([t]) => summaryRow(t)), [1600, 1300, 2900, 1400, 650, 1788], { center: [4], size: 16 }),
  para(C.finalNote, { size: 18, before: 80 }),
];

// ---------------------------------------------------------------- 간결본 (--short): 같은 내용, 중복 제거
//   빠지는 것: 양식 예시 표 4개(비정규 릴레이션과 중복), 2NF·3NF 결과 목록(분해표·2장과 중복),
//   1.6 이상 현상 요약(단계별 표와 중복), 2.2의 기본키·정규형 열(2.1과 중복, 모두 BCNF)
const ARGS = process.argv.slice(2);
const SHORT = ARGS.includes('--short');
const S = C.short;
const formLine = (f) => para([run(`${f.title.replace('양식 ', '')}  `, { size: 18, bold: true, color: '1F3864' }),
                              ...marked(f.unf, { size: 18 })], { after: 60, line: 270 });

const s1 = [
  h1('1. 정규화 진행 과정'),
  h2('1.1 출발점 — 비정규 릴레이션과 함수 종속'),
  para(S.intro),
  ...[C.formAccount, C.formCase, C.formLogLogin, C.formLogTransfer].map(formLine),
  gap(),
  table(['ID', '함수 종속'], C.fds.map(([id, fd]) => [id, fd + (S.fdNotes[id] || '')]), [800, 8838],
        { boldFirst: true, center: [0], size: 16 }),

  h2('1.2 제1정규형 (1NF) — 반복 그룹과 복합값 제거'),
  lead(C.nf1Intro),
  table(['위반 유형', '위치', '처리'], C.nf1, [1000, 3300, 5338], { boldFirst: true, center: [0], size: 16 }),
  para(S.nf1Keys, { before: 100 }),
  label(C.nf1Example.caption),
  table(C.nf1Example.headers, C.nf1Example.rows, C.nf1Example.widths, { size: 16, center: [1, 2, 3, 4, 7, 8, 9, 10] }),
  gap(),
  label('1NF 결과'),
  ...C.nf1Result.map((t) => para(t, { size: 17, bullet: true, after: 20, line: 260 })),

  h2('1.3 제2정규형 (2NF) — 부분 함수 종속 제거'),
  lead(S.nf2Intro),
  table(['릴레이션 (기본키)', '부분 함수 종속', '이상 현상', '분해 결과'], C.nf2, [1600, 2100, 2900, 3038], { boldFirst: true, size: 16 }),

  h2('1.4 제3정규형 (3NF) — 이행 함수 종속 제거'),
  lead(S.nf3Intro),
  table(['릴레이션', '이행 함수 종속', '이상 현상', '분해 결과'], C.nf3, [1100, 2500, 2700, 3338], { boldFirst: true, size: 16 }),
  gap(),
  ...S.nf3Notes.map((t) => para(t, { bullet: true, after: 40 })),

  h2('1.5 BCNF 검사와 구현에서 둔 유도 값'),
  para(S.bcnf),
  lead(S.derived),
  table(['생성 컬럼', '계산식'], C.derived.map(([c, f]) => [c, f]), [2600, 7038], { boldFirst: true, size: 16 }),
  para(S.acrossIntro, { before: 120 }),
  ...S.across.map((t) => para(t, { size: 18, bullet: true, after: 30, line: 270 })),
];

const s2 = [
  h1('2. 정규화를 적용한 테이블'),
  para(S.finalIntro),
  h2('2.1 관계 스키마'),
  para([run('표기: ', { size: 18 }), run('밑줄', { size: 18, underline: true }), run(' = 기본키, ', { size: 18 }),
        run('기울임', { size: 18, italics: true }), run(' = 외래키, ', { size: 18 }),
        run('회색', { size: 18, color: '8C8C8C' }), run(' = DBMS가 계산하는 생성 컬럼', { size: 18 })], { after: 100, keepNext: true }),
  ...C.finalTables.map(([t]) => schemaLine(t)),
  h2('2.2 외래키·UNIQUE 제약과 도출 단계'),
  table(['테이블', '외래키 → 참조 테이블', 'UNIQUE 제약', '도출 단계'],
        C.finalTables.map(([t]) => { const [name, , fks, uks, , step] = summaryRow(t); return [name, fks, uks, step]; }),
        [1700, 3900, 1800, 2238], { size: 16 }),
];

// ---------------------------------------------------------------- 문서
const header = new Header({ children: [para([run(C.meta.title, { size: 16, color: '808080' })], { align: AlignmentType.RIGHT, after: 0 })] });
const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
  children: [new TextRun({ children: ['- ', PageNumber.CURRENT, ' -'], font: FONT, size: 16, color: '808080' })] })] });

const doc = new Document({
  creator: C.meta.author, title: `${C.meta.title} — 정규화`,
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 30, bold: true }, paragraph: { outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 24, bold: true }, paragraph: { outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 21, bold: true }, paragraph: { outlineLevel: 2 } },
    ],
  },
  numbering: { config: [{ reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [{
    properties: { page: { size: PAGE, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134, header: 567, footer: 567 } } },
    headers: { default: header }, footers: { default: footer },
    children: SHORT ? [...cover, ...s1, ...s2] : [...cover, ...ch1, ...ch2],
  }],
});

const out = ARGS.find((a) => !a.startsWith('--')) || path.join(__dirname, 'norm.docx');
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log(`wrote ${out} (${buf.length} bytes)`); });
