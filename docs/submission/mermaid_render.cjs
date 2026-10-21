// Рендер блоков mermaid в SVG и PNG для PDF/DOCX документации (Chromium из Playwright).
// node mermaid_render.cjs <список.json> — [{"src": "...", "svg": "путь", "png": "путь"}]
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const MERMAID = require.resolve('mermaid/dist/mermaid.min.js');
(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const b = await chromium.launch({ args: ['--no-sandbox'], executablePath: process.env.CHROME || undefined });
  const p = await b.newPage({ deviceScaleFactor: 2, viewport: { width: 1100, height: 900 } });
  await p.setContent('<html><body style="margin:0;background:#fff"><div id="o"></div></body></html>');
  await p.addScriptTag({ path: MERMAID });
  await p.evaluate(() => mermaid.initialize({
    startOnLoad: false, theme: 'base', securityLevel: 'strict',
    themeVariables: { fontFamily: 'Montserrat, DejaVu Sans, sans-serif', fontSize: '15px', primaryColor: '#EEF0FF',
      primaryBorderColor: '#402FFF', primaryTextColor: '#0A0B1F', lineColor: '#5F57B8', actorBkg: '#EEF0FF',
      actorBorder: '#402FFF', noteBkgColor: '#FFF4F6', noteBorderColor: '#EC1D35', signalColor: '#0A0B1F',
      signalTextColor: '#0A0B1F', labelBoxBkgColor: '#EEF0FF', altBackground: '#F7F7FC' },
    sequence: { mirrorActors: false, useMaxWidth: false, wrap: true, width: 230, actorMargin: 70, messageMargin: 32, boxMargin: 8 },
    flowchart: { useMaxWidth: false, htmlLabels: false, nodeSpacing: 40, rankSpacing: 50 }, htmlLabels: false,
  }));
  let i = 0;
  for (const j of jobs) {
    const { svg } = await p.evaluate(async ([s, id]) => mermaid.render(id, s), [j.src, 'm' + (i++)]);
    fs.mkdirSync(path.dirname(j.svg), { recursive: true });
    fs.writeFileSync(j.svg, svg);
    await p.evaluate((s) => { document.getElementById('o').innerHTML = s; }, svg);
    const el = await p.$('#o svg');
    await el.screenshot({ path: j.png, omitBackground: false });
    console.log('  диаграмма', path.basename(j.png));
  }
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
