// 물리 설계 제출본: ① 모든 테이블(컬럼) ② 제약 명세 ③ 참조 무결성 / 삭제 정책
//   node build_phys.js <출력 경로>
// 타입·NULL·키·기본값·FK 대상·ON DELETE/UPDATE 는 실제 DB 카탈로그(phys_catalog.json, scripts/export_physical_json.py)에서
// 채우고, 설명·이유는 content_phys.js 에서 가져온다. 둘이 어긋나면(빠진 컬럼·제약, 없는 이름) 빌드가 실패한다.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, Header, Footer,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, VerticalAlign,
  PageNumber, TableLayoutType,
} = require('docx');
const C = require('./content_phys');
const CAT = JSON.parse(fs.readFileSync(path.join(__dirname, 'phys_catalog.json'), 'utf-8'));

const FONT = 'Malgun Gothic';
const W = 11906 - 2 * 1134;                   // A4, 여백 20mm → 본문 폭 9638 DXA
const PAGE = { width: 11906, height: 16838 };

// ---------------------------------------------------------------- 기본 요소
const run = (text, o = {}) => new TextRun({ text, font: FONT, size: o.size || 20, bold: o.bold, color: o.color });
const para = (text, o = {}) => new Paragraph({
  children: Array.isArray(text) ? text : [run(text, o)],
  alignment: o.align, spacing: { before: o.before || 0, after: o.after ?? 100, line: o.line || 300 },
  keepNext: o.keepNext,
});
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(text, { size: 30, bold: true })], spacing: { before: 280, after: 160 }, keepNext: true });
const label = (text) => para(text, { size: 18, bold: true, color: '1F3864', before: 120, after: 60, keepNext: true });
const gap = () => para('', { after: 40 });

const border = { style: BorderStyle.SINGLE, size: 4, color: '8C8C8C' };
const BORDERS = { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border };

function cell(content, width, o = {}) {
  // { scope, names } = FK 범위 + 그 아래 작은 글씨로 외래키 이름
  const lines = content && content.scope
    ? [[content.scope, { bold: true }], ...content.names.map((n) => [n, { size: 14, color: '555555' }])]
    : String(content).split('\n').map((line) => [line, { bold: o.bold }]);
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    margins: { top: 25, bottom: 25, left: 80, right: 80 },
    verticalAlign: VerticalAlign.CENTER,
    children: lines.map(([line, style]) => new Paragraph({
      children: [run(line, { size: o.size || 16, ...style })],
      alignment: o.center ? AlignmentType.CENTER : AlignmentType.LEFT,
      spacing: { after: 0, line: 230 }, keepNext: o.keepNext,
    })),
  });
}

// keepTogether: 마지막 행만 빼고 다음 행과 붙여, 한 쪽에 들어가는 표는 쪽 사이에서 잘리지 않게 한다
function table(headers, rows, widths, o = {}) {
  if (widths.reduce((a, b) => a + b, 0) !== W) throw new Error(`table width != ${W}: ${headers}`);
  const center = new Set(o.center || []);
  const out = [new TableRow({ tableHeader: true, cantSplit: true,
    children: headers.map((h, i) => cell(h, widths[i], { bold: true, fill: 'DCE6F2', center: true, keepNext: true })) })];
  rows.forEach((r, n) => out.push(new TableRow({ cantSplit: true,
    children: r.map((c, i) => cell(c, widths[i], {
      bold: o.boldFirst && i === 0, center: center.has(i), keepNext: o.keepTogether && n < rows.length - 1,
    })) })));
  return new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: widths, borders: BORDERS, rows: out,
                    layout: TableLayoutType.FIXED });
}

// ---------------------------------------------------------------- 카탈로그와 본문 대조
const fail = (msg) => { throw new Error(`content_phys.js ↔ phys_catalog.json: ${msg}`); };
const sameSet = (what, a, b) => {
  const A = new Set(a), B = new Set(b);
  const onlyA = [...A].filter((x) => !B.has(x)), onlyB = [...B].filter((x) => !A.has(x));
  if (onlyA.length || onlyB.length || a.length !== A.size) fail(`${what} — 본문에만: [${onlyA}] / DB에만: [${onlyB}]`);
};
const allCons = (type) => Object.values(CAT).flatMap((t) => t.constraints.filter((k) => k.type === type));

sameSet('테이블', C.tables.map((t) => t[0]), Object.keys(CAT));
C.tables.forEach(([t, , desc]) => sameSet(`${t} 컬럼`, Object.keys(desc), CAT[t].columns.map((c) => c.name)));
sameSet('UNIQUE', C.uniques.flatMap((r) => r[0]),
        [...allCons('u').map((k) => k.name), ...Object.values(CAT).flatMap((t) => t.partial_uniques.map((p) => p.name))]);
sameSet('CHECK', C.checks.flatMap((r) => r[0]), allCons('c').map((k) => k.name));
sameSet('FK', C.fkPolicy.flatMap((r) => r[2]), allCons('f').map((k) => k.name));

// ---------------------------------------------------------------- 1. 모든 테이블
const tuple = (cols) => (cols.length > 1 ? `(${cols.join(', ')})` : cols[0]);

function columnRows(t, desc) {
  const cons = CAT[t].constraints;
  const pk = cons.find((k) => k.type === 'p').cols;
  return CAT[t].columns.map((c) => {
    const fks = cons.filter((k) => k.type === 'f' && k.cols.includes(c.name));
    const uks = cons.filter((k) => k.type === 'u' && k.cols.includes(c.name));
    const key = [
      pk.includes(c.name) ? (pk.length > 1 ? '복합 PK' : 'PK') : null,
      fks.length ? (fks.some((k) => k.cols.length === 1) ? 'FK' : '복합 FK') : null,
      uks.some((k) => k.cols.length === 1) ? 'UK' : null,
      uks.some((k) => k.cols.length > 1) ? '복합 UK' : null,
    ].filter(Boolean).join(' / ');
    const note = [
      c.identity ? 'IDENTITY' : null,
      c.default ? `DEFAULT ${c.default}` : null,
      ...fks.map((k) => `→ ${k.ref}${k.cols.length > 1 ? `(${k.refcols.join(', ')})` : `.${k.refcols[0]}`}`),
      c.generated ? `생성 컬럼 ${desc[c.name]}` : desc[c.name],
    ].filter(Boolean).join('; ');
    return [c.name, c.type, c.notnull ? 'N' : 'Y', key, note];
  });
}

const ch1 = [
  h1('1. 모든 테이블'),
  para(C.tablesIntro),
  ...C.tables.flatMap(([t, ko, desc]) => [
    para([run(t, { size: 20, bold: true, color: '1F3864' }), run(`   ${ko}`, { size: 18, color: '555555' })],
         { before: 140, after: 50, keepNext: true }),
    table(['컬럼', '타입', 'NULL', '키', '기본값 / 규칙 / 설명'], columnRows(t, desc), [2300, 1200, 650, 1300, 4188],
          { boldFirst: true, center: [2, 3], keepTogether: CAT[t].columns.length <= 6 }),   // 큰 표는 쪽을 넘겨도 됨(머리행 반복)
  ]),
];

// ---------------------------------------------------------------- 2. 제약 명세
const conRows = (rows) => rows.map(([names, target, why]) => [names.join('\n'), target, why]);
const ch2 = [
  h1('2. 제약 명세'),
  para(C.constraintsIntro),
  label(`UNIQUE — 제약 ${allCons('u').length}개, 부분 UNIQUE 인덱스 ${C.uniques.flatMap((r) => r[0]).length - allCons('u').length}개`),
  table(['제약명', '대상', '이유'], conRows(C.uniques), [2900, 3500, 3238], { boldFirst: true }),
  gap(),
  label(`CHECK — ${C.checks.flatMap((r) => r[0]).length}개`),
  table(['제약명', '대상', '이유'], conRows(C.checks), [2900, 3500, 3238], { boldFirst: true }),
];

// ---------------------------------------------------------------- 3. 참조 무결성 / 삭제 정책
const fkByName = Object.fromEntries(allCons('f').map((k) => [k.name, k]));
const fkRows = C.fkPolicy.map(([scope, why, names]) => {
  const acts = (field) => [...new Set(names.map((n) => fkByName[n][field]))];
  const del = acts('on_delete'), upd = acts('on_update');
  if (del.length !== 1 || upd.length !== 1) fail(`FK 묶음 안의 동작이 다름: ${names}`);
  return [{ scope, names }, del[0], upd[0], why];
});
const ch3 = [
  h1('3. 참조 무결성 / 삭제 정책'),
  ...C.fkIntro.map((t) => para(t)),
  table(['FK 범위 (자식 → 부모) / 제약명', 'ON DELETE', 'ON UPDATE', '근거'], fkRows, [3350, 1150, 1150, 3988],
        { center: [1, 2] }),
  // 표가 쪽 끝에서 끝나도 Word가 표 뒤에 두는 빈 문단 때문에 빈 쪽이 생기지 않게 한다
  new Paragraph({ spacing: { before: 0, after: 0, line: 20, lineRule: 'exact' }, children: [new TextRun({ text: '', size: 2 })] }),
];

// ---------------------------------------------------------------- 문서
const cover = [
  para(C.meta.course, { size: 18, color: '555555', after: 40 }),
  para(C.meta.title, { size: 36, bold: true, after: 60 }),
  para(C.meta.subtitle, { size: 22, color: '1F3864', after: 160 }),
  new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: [1000, 2600, 1000, 2000, 900, 2138], borders: BORDERS,
    layout: TableLayoutType.FIXED,
    rows: [new TableRow({ children: ['작성자', C.meta.author, '작성일', C.meta.date, '버전', C.meta.version]
      .map((c, i) => cell(c, [1000, 2600, 1000, 2000, 900, 2138][i], { size: 17 })) })] }),
  gap(),
];
const header = new Header({ children: [para([run(C.meta.title, { size: 16, color: '808080' })], { align: AlignmentType.RIGHT, after: 0 })] });
const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
  children: [new TextRun({ children: ['- ', PageNumber.CURRENT, ' -'], font: FONT, size: 16, color: '808080' })] })] });

const doc = new Document({
  creator: C.meta.author, title: `${C.meta.title} — 물리 설계`,
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 30, bold: true }, paragraph: { outlineLevel: 0 } },
    ],
  },
  sections: [{
    properties: { page: { size: PAGE, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134, header: 567, footer: 567 } } },
    headers: { default: header }, footers: { default: footer },
    children: [...cover, ...ch1, ...ch2, ...ch3],
  }],
});

const out = process.argv[2] || path.join(__dirname, 'phys.docx');
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log(`wrote ${out} (${buf.length} bytes)`); });
