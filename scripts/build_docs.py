"""5주차 제출 문서를 PDF로 만든다 (Microsoft Edge 헤드리스 인쇄).

    python scripts/gen_schema_doc.py   # 먼저 DB에서 논리 스키마 표를 갱신
    python scripts/build_docs.py

출력: docs/05_conceptual_design.pdf (ERD + 설명, A4 가로 1쪽)
      docs/05_logical_design.pdf    (관계 스키마·PK/FK·제약조건·정규화 근거)
      docs/erd.png                  (ERD 이미지 — 보고서·발표용)
한글 사용자 폴더 경로 문제를 피하려고 C:\\pgtemp\\render 에서 렌더링한 뒤 복사한다.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
WORK = Path(r'C:\pgtemp\render')
EDGE = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')

CSS = """
@page { size: A4 %(orient)s; margin: %(margin)s; }
body { font-family: 'Malgun Gothic', sans-serif; font-size: %(font)s; line-height: 1.45; color: #111; margin: 0; }
h1 { font-size: 15pt; margin: 0 0 6px; }
h2 { font-size: 11.5pt; margin: 12px 0 4px; border-bottom: 1px solid #999; padding-bottom: 2px; }
p, li { margin: 2px 0; }
ul, ol { margin: 2px 0 4px; padding-left: 18px; }
table { border-collapse: collapse; width: 100%%; margin: 4px 0; }
th, td { border: 1px solid #aaa; padding: 2px 5px; text-align: left; vertical-align: top; }
th { background: #eee; }
code { font-family: Consolas, monospace; font-size: 0.92em; }
.erd { text-align: center; margin: 0 0 4px; }
.erd svg { width: 100%% !important; max-width: 100%% !important; height: auto; max-height: %(erd_h)s; }
"""

MERMAID = """
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  import elkLayouts from 'https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0/dist/mermaid-layout-elk.esm.min.mjs';
  mermaid.registerLayoutLoaders(elkLayouts);
  mermaid.initialize({ startOnLoad: false, theme: 'neutral', layout: 'elk', themeVariables: { fontSize: '17px' },
                       er: { useMaxWidth: true }, fontFamily: 'Malgun Gothic' });
  const { svg } = await mermaid.render('erdsvg', document.getElementById('erd-src').textContent);
  document.getElementById('erd').innerHTML = svg;
</script>
"""


def html_page(body_md: str, css: dict, erd_src: str = '') -> str:
    body = markdown.markdown(body_md, extensions=['tables'])
    if erd_src:
        body = body.replace('<!--ERD-->', '<div class="erd" id="erd"></div>')
        extra = f'<script type="text/plain" id="erd-src">{erd_src}</script>{MERMAID}'
    else:
        extra = ''
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS % css}</style></head>' \
           f'<body>{body}{extra}</body></html>'


def edge(args: list) -> None:
    subprocess.run([str(EDGE), '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                    '--virtual-time-budget=20000', *args], check=True, capture_output=True, timeout=120)


def render(name: str, html: str, screenshot: str = '') -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    src = WORK / f'{name}.html'
    src.write_text(html, encoding='utf-8')
    pdf = WORK / f'{name}.pdf'
    pdf.unlink(missing_ok=True)
    edge([f'--print-to-pdf={pdf}', src.as_uri()])
    shutil.copy2(pdf, DOCS / pdf.name)
    if screenshot:
        png = WORK / screenshot
        edge([f'--screenshot={png}', '--window-size=1600,1130', src.as_uri()])
        shutil.copy2(png, DOCS / screenshot)
    return DOCS / pdf.name


def render_png(name: str, erd_src: str, size: str) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    src = WORK / f'{name}.html'
    src.write_text(html_page('<!--ERD-->', {'orient': 'landscape', 'margin': '0', 'font': '10pt', 'erd_h': '97vh'},
                             erd_src), encoding='utf-8')
    png = WORK / f'{name}.png'
    edge([f'--screenshot={png}', f'--window-size={size}', src.as_uri()])
    shutil.copy2(png, DOCS / png.name)


def main() -> int:
    conceptual = (DOCS / '05_conceptual_design.md').read_text(encoding='utf-8')
    out1 = render('05_conceptual_design',
                  html_page(conceptual, {'orient': 'landscape', 'margin': '8mm 10mm', 'font': '8.6pt',
                                         'erd_h': '132mm'}, (DOCS / 'erd_conceptual.mmd').read_text(encoding='utf-8')),
                  screenshot='erd_conceptual_preview.png')
    # 속성까지 넣은 전체 ERD — 보고서·발표용 이미지 (큰 화면에 단독 렌더링)
    render_png('erd_full', (DOCS / 'erd.mmd').read_text(encoding='utf-8'), size='3200,1150')

    logical = '# Logical Design — 관계 스키마 · PK/FK\n\n' + \
        (DOCS / 'schema_catalog.md').read_text(encoding='utf-8').split('\n', 2)[2] + '\n' + \
        (DOCS / '05_normalization.md').read_text(encoding='utf-8')
    out2 = render('05_logical_design',
                  html_page(logical, {'orient': 'portrait', 'margin': '10mm 12mm', 'font': '8.4pt', 'erd_h': '0'}))
    for p in (out1, out2):
        print(f'wrote {p.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
