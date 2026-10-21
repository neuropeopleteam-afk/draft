#!/usr/bin/env python3
"""DOCUMENTATION.md → DOCUMENTATION.pdf и DOCUMENTATION.docx (вызывается из build.py).

Диаграммы mermaid рендерятся в SVG (для PDF) и PNG (для DOCX) в docs/submission/assets/.
PDF — HTML от pandoc + печать Chromium (оглавление, номера страниц); DOCX — pandoc с оглавлением.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = HERE / "out" / "DOCUMENTATION.pandoc.md"  # собирает build.py
ASSETS = HERE / "assets"
NODE_MODULES = ROOT / "docs/presentation/node_modules"


def chrome() -> str:
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    c = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    if not c:
        sys.exit("нет Chromium: npx playwright install chromium")
    return c[-1]


def node_env() -> dict:
    env = dict(os.environ, NODE_PATH=str(NODE_MODULES), CHROME=chrome())
    return env


def render_mermaid(md: str) -> tuple[str, str]:
    """Возвращает (md для HTML со ссылками на SVG, md для DOCX со ссылками на PNG)."""
    blocks = list(re.finditer(r"```mermaid\n(.*?)```", md, re.S))
    jobs = []
    for i, m in enumerate(blocks, 1):
        jobs.append({"src": m.group(1), "svg": str(ASSETS / f"diagram_{i}.svg"), "png": str(ASSETS / f"diagram_{i}.png")})
    if jobs:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(jobs, f, ensure_ascii=False)
        subprocess.run(["node", str(HERE / "mermaid_render.cjs"), f.name], check=True, env=node_env())
    html_md, docx_md = md, md
    for i, m in reversed(list(enumerate(blocks, 1))):
        html_md = html_md[:m.start()] + f'<div class="diagram"><img src="assets/diagram_{i}.png" alt="Схема {i}"></div>' + html_md[m.end():]
        docx_md = docx_md[:m.start()] + f"![](assets/diagram_{i}.png){{width=16cm}}" + docx_md[m.end():]
    return html_md, docx_md


CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 18mm; }
html { font-family: Montserrat, 'DejaVu Sans', sans-serif; font-size: 9.6pt; color: #0A0B1F; line-height: 1.45; }
body { margin: 0; }
h1 { font-size: 17pt; color: #0A0B1F; margin: 0 0 8pt; padding-top: 4pt; border-bottom: 2pt solid #402FFF; padding-bottom: 4pt; break-before: page; }
h2 { font-size: 12.5pt; color: #2B1FD6; margin: 14pt 0 5pt; break-after: avoid; }
h3 { font-size: 11pt; margin: 10pt 0 4pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #3A28F0; text-decoration: none; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.2pt; background: #F1F2FA; padding: 0 2pt; border-radius: 2pt; word-break: break-word; }
pre { background: #F1F2FA; padding: 6pt 8pt; border-radius: 4pt; white-space: pre-wrap; font-size: 8.2pt; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 8pt; font-size: 8.4pt; break-inside: auto; }
th { background: #EEF0FF; color: #0A0B1F; text-align: left; font-weight: 600; }
th, td { border: 0.6pt solid #C9CCE6; padding: 3pt 5pt; vertical-align: top; word-break: break-word; }
tr { break-inside: avoid; }
ol li, ul li { margin: 1.5pt 0; }
.diagram { text-align: center; margin: 8pt 0; break-inside: avoid; }
.diagram img { max-width: 100%; max-height: 125mm; }
header#title-block-header { break-after: page; padding-top: 70mm; border-top: 6pt solid #402FFF; }
header#title-block-header .title { font-size: 30pt; border: none; break-before: avoid; margin-bottom: 10pt; }
header#title-block-header .subtitle { font-size: 14pt; color: #2B1FD6; font-weight: 500; margin: 0 0 30pt; }
header#title-block-header .author, header#title-block-header .date { font-size: 11pt; color: #3B3D5C; margin: 4pt 0; }
nav#TOC { break-after: page; }
nav#TOC::before { content: "Содержание"; display: block; font-size: 17pt; font-weight: 700; border-bottom: 2pt solid #402FFF; margin-bottom: 8pt; padding-bottom: 4pt; }
nav#TOC ul { list-style: none; padding-left: 12pt; } nav#TOC > ul { padding-left: 0; }
nav#TOC li { margin: 2pt 0; } nav#TOC > ul > li > a { font-weight: 600; }
"""


def build_pdf(html_md: str) -> None:
    tmp = HERE / "_doc.md"
    tmp.write_text(html_md, encoding="utf-8")
    css = HERE / "_doc.css"
    css.write_text(CSS, encoding="utf-8")
    html = HERE / "_doc.html"
    subprocess.run(["pandoc", str(tmp), "-f", "markdown+header_attributes", "-t", "html5", "--standalone", "--toc",
                    "--toc-depth=2", "--number-sections", "--css", css.name, "-o", str(html)], check=True, cwd=HERE)
    footer = ('<div style="font-family:Montserrat,sans-serif;font-size:7pt;color:#5A5C7A;width:100%;padding:0 16mm 0 18mm;'
              'display:flex;justify-content:space-between"><span>«Драфт» — техническая документация</span>'
              '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    js = f"""
const {{ chromium }} = require('playwright');
(async () => {{
  const b = await chromium.launch({{ args: ['--no-sandbox'], executablePath: process.env.CHROME }});
  const p = await b.newPage();
  await p.goto('file://{html}', {{ waitUntil: 'networkidle' }});
  await p.pdf({{ path: '{HERE / "DOCUMENTATION.pdf"}', format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>', footerTemplate: {json.dumps(footer)},
    margin: {{ top: '16mm', bottom: '16mm', left: '0', right: '0' }} }});
  await b.close();
}})();
"""
    jf = HERE / "_pdf.cjs"
    jf.write_text(js, encoding="utf-8")
    subprocess.run(["node", str(jf)], check=True, env=node_env())
    for f in (tmp, css, html, jf):
        f.unlink(missing_ok=True)
    print("  записано docs/submission/DOCUMENTATION.pdf")


def build_docx(docx_md: str) -> None:
    tmp = HERE / "_docx.md"
    tmp.write_text(docx_md, encoding="utf-8")
    ref = HERE / "assets/reference.docx"
    if not ref.exists():
        make_reference(ref)
    subprocess.run(["pandoc", str(tmp), "-f", "markdown+header_attributes", "-t", "docx", "--toc", "--toc-depth=2",
                    "--number-sections", "-M", "toc-title=Содержание", f"--reference-doc={ref}", "-o", str(HERE / "DOCUMENTATION.docx")],
                   check=True, cwd=HERE)
    tmp.unlink(missing_ok=True)
    print("  записано docs/submission/DOCUMENTATION.docx")


def make_reference(ref: Path) -> None:
    """Стили Word: шрифт Montserrat (как на сайте), цвета бренда, таблицы с сеткой."""
    subprocess.run(["pandoc", "-o", str(ref), "--print-default-data-file", "reference.docx"], check=True)
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    d = Document(str(ref))
    for st in d.styles:
        el = st.element
        rpr = el.find(qn("w:rPr"))
        if rpr is None and st.type in (1, 3):
            rpr = OxmlElement("w:rPr")
            el.append(rpr)
        if rpr is None:
            continue
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for k in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rf.get(qn(k)) is not None:
                del rf.attrib[qn(k)]
        mono = st.name in ("Source Code", "Verbatim Char")
        for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(k), "DejaVu Sans Mono" if mono else "Montserrat")
    d.styles["Normal"].font.size = Pt(10)
    for name, size, color in (("Heading 1", 16, "0A0B1F"), ("Heading 2", 13, "2B1FD6"), ("Heading 3", 11, "0A0B1F"),
                              ("Title", 26, "0A0B1F"), ("Subtitle", 14, "2B1FD6")):
        if name in d.styles:
            d.styles[name].font.size = Pt(size)
            d.styles[name].font.color.rgb = RGBColor.from_string(color)
    if "Table" in [x.name for x in d.styles]:
        tpr = d.styles["Table"].element.find(qn("w:tblPr"))
        if tpr is None:
            tpr = OxmlElement("w:tblPr")
            d.styles["Table"].element.append(tpr)
        b = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{side}")
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), "4")
            e.set(qn("w:color"), "C9CCE6")
            b.append(e)
        tpr.append(b)
    d.save(str(ref))


def main() -> int:
    md = SRC.read_text(encoding="utf-8")
    html_md, docx_md = render_mermaid(md)
    build_pdf(html_md)
    build_docx(docx_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
