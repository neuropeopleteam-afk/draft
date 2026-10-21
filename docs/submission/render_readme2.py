#!/usr/bin/env python3
"""README_2.md → docs/submission/README_2.pdf (A4 альбомная: таблица «было → стало» широкая).
Вызывается из build.py после сборки README_2.md; отдельно: python3 docs/submission/render_readme2.py"""
import json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_docs import HERE, ROOT, node_env  # noqa: E402

CSS = """
@font-face { font-family: Montserrat; src: local('Montserrat'); }
body { font-family: Montserrat, 'DejaVu Sans', sans-serif; font-size: 9pt; color: #1B1C3A; margin: 0 14mm; line-height: 1.35; }
h1 { font-size: 17pt; color: #310F53; margin: 0 0 6pt; } h2 { font-size: 12.5pt; color: #520978; margin: 14pt 0 5pt; }
a { color: #520978; } code { font-size: 8pt; background: #F3EEF9; padding: 0 2px; border-radius: 2px; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; } th { background: #310F53; color: #fff; text-align: left; font-weight: 600; }
th, td { border: 0.5pt solid #D9CFE8; padding: 3pt 5pt; vertical-align: top; }
tbody tr:nth-child(even) td { background: #FBF8FE; }
"""


def main() -> None:
    md = (ROOT / "README_2.md").read_text(encoding="utf-8")
    md = re.sub(r"<!--.*?-->\n?", "", md, flags=re.S)
    # ссылки на файлы репозитория — на GitHub, чтобы работали из PDF
    md = re.sub(r"\]\((?!https?://|#)([^)]+)\)", r"](https://github.com/neuropeopleteam-afk/draft/blob/main/\1)", md)
    tmp, css, html = HERE / "_r2.md", HERE / "_r2.css", HERE / "_r2.html"
    tmp.write_text(md, encoding="utf-8"); css.write_text(CSS, encoding="utf-8")
    subprocess.run(["pandoc", str(tmp), "-f", "gfm", "-t", "html5", "--standalone", "--metadata", "title=README 2",
                    "--css", css.name, "-o", str(html)], check=True, cwd=HERE)
    h = html.read_text(encoding="utf-8").replace('<header id="title-block-header">\n<h1 class="title">README 2</h1>\n</header>', "")
    html.write_text(h, encoding="utf-8")
    out = HERE / "README_2.pdf"
    footer = ('<div style="font-family:Montserrat,sans-serif;font-size:7pt;color:#5A5C7A;width:100%;padding:0 14mm;'
              'display:flex;justify-content:space-between"><span>«Драфт» — что было на отборе и что стало к финалу</span>'
              '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    js = f"""
const {{ chromium }} = require('playwright');
(async () => {{
  const b = await chromium.launch({{ args: ['--no-sandbox'], executablePath: process.env.CHROME }});
  const p = await b.newPage();
  await p.goto('file://{html}', {{ waitUntil: 'networkidle' }});
  await p.pdf({{ path: '{out}', format: 'A4', landscape: true, printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>', footerTemplate: {json.dumps(footer)},
    margin: {{ top: '12mm', bottom: '14mm', left: '0', right: '0' }} }});
  await b.close();
}})();
"""
    jf = HERE / "_r2.cjs"; jf.write_text(js, encoding="utf-8")
    subprocess.run(["node", str(jf)], check=True, env=node_env())
    for f in (tmp, css, html, jf):
        f.unlink(missing_ok=True)
    print("  записано docs/submission/README_2.pdf")


if __name__ == "__main__":
    main()
