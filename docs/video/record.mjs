// Черновик видео «Драфт» (3 мин): запись экрана сайта по сценам docs/video/SCRIPT.md + титры. Без голоса.
//   DRAFT_ENTRY=https://fsp-draft.ru/ node docs/video/record.mjs
// DRAFT_ENTRY — адрес первого входа (например, личная ссылка эксперта); DRAFT_BASE — адрес сайта (по умолчанию —
// источник DRAFT_ENTRY). Результат: docs/video/out/draft_video.mp4 (+ scenes.json с тайм-кодами). Нужны playwright, ffmpeg.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, 'out');
const ENTRY = process.env.DRAFT_ENTRY || 'https://fsp-draft.ru/';
const BASE = process.env.DRAFT_BASE || new URL(ENTRY).origin;
const W = 1280, H = 720;
fs.mkdirSync(OUT, { recursive: true });

// Титры — столбец «Титр» сценария (docs/video/SCRIPT.md); длительности — столбец «Время».
const script = fs.readFileSync(path.join(HERE, 'SCRIPT.md'), 'utf8');
const rows = script.split('\n').filter((l) => /^\| \d+ \|/.test(l)).map((l) => l.split('|').map((c) => c.trim()));
const toSec = (t) => { const [m, s] = t.split(':').map(Number); return m * 60 + s; };
const scenes = rows.map((r) => { const [a, b] = r[2].split('–'); return { n: Number(r[1]), dur: toSec(b) - toSec(a), title: r[5] }; });

async function scroll(p, px, ms) {
  // плавный скролл по времени: ровно ms миллисекунд
  const end = Date.now() + ms;
  const step = Math.max(1, px / Math.max(1, ms / 120));
  while (Date.now() < end) { await p.mouse.wheel(0, step).catch(() => {}); await p.waitForTimeout(120); }
}
async function go(p, url) {
  await p.goto(BASE + url, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
  await p.waitForTimeout(800);
}
async function role(p, name) {
  await go(p, '/demo');
  const anchor = p.locator('#jury-roles-anchor');
  if (await anchor.count()) await anchor.scrollIntoViewIfNeeded().catch(() => {});
  const btn = p.getByRole('button', { name, exact: true }).first();
  await btn.click({ timeout: 20000 }).catch(() => {});
  await p.waitForLoadState('networkidle', { timeout: 90000 }).catch(() => {});
  await p.waitForTimeout(1500);
}

// Действия сцен 1–10 (как в сценарии). Каждая сцена длится dur секунд: недостающее время — медленный скролл.
const ACTIONS = {
  1: async (p) => { await go(p, '/'); },
  2: async (p) => { await scroll(p, 900, 1500); },
  3: async (p) => { await role(p, 'Кандидат'); await go(p, '/candidate/assessment'); },
  4: async (p) => { await go(p, '/candidate/category'); },
  5: async (p) => { await role(p, 'Работодатель'); await go(p, '/employer/needs'); },
  6: async (p) => { await go(p, '/employer/search'); },
  7: async (p) => { await role(p, 'Кандидат'); await go(p, '/candidate/fsp'); },
  8: async (p) => { await go(p, '/validation'); },
  9: async (p) => { await go(p, '/api/docs'); },
  10: async (p) => { await go(p, '/demo'); },
};

// Запись: кадры экрана через CDP (Page.startScreencast) с метками времени → склейка ffmpeg.
const FR = path.join(OUT, 'frames');
fs.rmSync(FR, { recursive: true, force: true });
fs.mkdirSync(FR, { recursive: true });
const b = await chromium.launch({ args: ['--no-sandbox'], executablePath: process.env.CHROME || undefined });
const ctx = await b.newContext({ viewport: { width: W, height: H }, ignoreHTTPSErrors: true, locale: 'ru-RU' });
const p = await ctx.newPage();
await p.goto(ENTRY, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
const cdp = await ctx.newCDPSession(p);
const frames = []; // {t, file}
cdp.on('Page.screencastFrame', async (f) => {
  const file = path.join(FR, `f${String(frames.length).padStart(6, '0')}.jpg`);
  fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
  frames.push({ t: Date.now() / 1000, file });
  await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
});
await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 82, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
const marks = [];
for (const s of scenes) {
  const start = Date.now() / 1000;
  await (ACTIONS[s.n] || (async () => {}))(p);
  // после действия сцена держится ещё dur секунд (в ролик идут последние dur секунд — без ожидания загрузки)
  await scroll(p, s.n === 1 ? 300 : 900, s.dur * 1000);
  marks.push({ ...s, start, end: Date.now() / 1000 });
  console.log(`  сцена ${s.n}: ${(marks.at(-1).end - start).toFixed(1)} с записи, в ролик — ${s.dur} с`);
}
await cdp.send('Page.stopScreencast').catch(() => {});
await ctx.close();
await b.close();

// Склейка: для каждой сцены — кадры последних dur секунд; длительность кадра — до следующего кадра.
const lines = ['ffconcat version 1.0'];
let tl = 0;
const caps = [];
for (const m of marks) {
  const from = m.end - m.dur;
  let fs_ = frames.filter((f) => f.t >= from && f.t <= m.end);
  const before = frames.filter((f) => f.t < from).at(-1);
  if (before) fs_ = [{ ...before, t: from }, ...fs_];
  if (!fs_.length) continue;
  fs_.forEach((f, i) => {
    const next = i + 1 < fs_.length ? fs_[i + 1].t : m.end;
    lines.push(`file '${f.file}'`, `duration ${Math.max(0.04, next - f.t).toFixed(3)}`);
  });
  caps.push({ title: m.title, a: tl, b: tl + m.dur });
  tl += m.dur;
}
lines.push(`file '${frames.at(-1).file}'`);
fs.writeFileSync(path.join(OUT, 'frames.ffconcat'), lines.join('\n'));
fs.writeFileSync(path.join(OUT, 'scenes.json'), JSON.stringify(caps, null, 1));
const esc = (t) => t.replace(/\\/g, '\\\\').replace(/:/g, '\\:').replace(/'/g, '’').replace(/%/g, '\\%').replace(/,/g, '\\,');
const font = process.env.CAPTION_FONT || '/usr/share/fonts/truetype/montserrat/Montserrat-SemiBold.ttf';
const fontArg = fs.existsSync(font) ? `fontfile='${font}':` : "font='Montserrat':";
const filters = caps.map((c) => `drawtext=${fontArg}text='${esc(c.title)}':x=48:y=h-96:fontsize=30:fontcolor=white:box=1:boxcolor=0x0A0B1F@0.78:boxborderw=18:enable='between(t,${c.a.toFixed(2)},${c.b.toFixed(2)})'`);
filters.push(`drawtext=${fontArg}text='Черновик · без голоса · fsp-draft.ru':x=w-tw-36:y=28:fontsize=18:fontcolor=white@0.85:box=1:boxcolor=0x402FFF@0.6:boxborderw=8`);
const out = path.join(OUT, 'draft_video.mp4');
execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', path.join(OUT, 'frames.ffconcat'),
  '-vf', `scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,fps=25,` + filters.join(','),
  '-t', String(tl), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p', '-an', out], { stdio: 'inherit' });
fs.rmSync(FR, { recursive: true, force: true });
console.log('  записано', path.relative(process.cwd(), out), `(${tl} с)`);
