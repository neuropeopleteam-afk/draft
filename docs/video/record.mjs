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
  await p.goto(BASE + url, { waitUntil: 'load', timeout: 45000 }).catch((e) => console.log(`  ${url}: ${e.message.split('\n')[0]}`));
  await p.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => {});
  await p.waitForTimeout(800);
  await hideGuide(p);
}
async function role(p, name) {
  // кнопки входа в демо-роль на /demo: подпись «Кандидат», доступное имя «Войти как: Кандидат»
  await go(p, '/demo');
  await cookies(p);
  const btn = p.locator('#jury-roles-anchor button').filter({ hasText: new RegExp(`^\\s*${name.replace(/[()]/g, '\\$&')}\\s*$`) }).first();
  await btn.scrollIntoViewIfNeeded().catch(() => {});
  await btn.click({ timeout: 20000 }).catch((e) => console.log(`  роль «${name}»: ${e.message.split('\n')[0]}`));
  await p.waitForLoadState('networkidle', { timeout: 90000 }).catch(() => {});
  await p.waitForTimeout(1500);
}
async function hideGuide(p) {
  // боковая панель «Проверка за 12 минут» закрывает половину кабинета — в ролике её прячем
  const b = p.getByRole('button', { name: 'Скрыть проводник', exact: true }).first();
  if (await b.count() && await b.isVisible().catch(() => false)) { await b.click({ timeout: 3000 }).catch(() => {}); await p.waitForTimeout(500); }
}
async function cookies(p) {
  await p.getByRole('button', { name: 'Только необходимые' }).click({ timeout: 2500 }).catch(() => {});
}
async function click(p, text, { exact = false, wait = 1500 } = {}) {
  const el = p.getByText(text, { exact }).first();
  if (!(await el.count())) { console.log(`  нет на экране: «${text}»`); return false; }
  await el.scrollIntoViewIfNeeded().catch(() => {});
  await p.waitForTimeout(500);
  await el.click({ timeout: 10000 }).catch((e) => console.log(`  «${text}»: ${e.message.split('\n')[0]}`));
  await p.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
  await p.waitForTimeout(wait);
  return true;
}
async function show(p, selectorOrText) {
  const el = typeof selectorOrText === 'string' && /^[#.\[]/.test(selectorOrText) ? p.locator(selectorOrText).first() : p.getByText(selectorOrText).first();
  if (await el.count()) { await el.scrollIntoViewIfNeeded().catch(() => {}); await p.waitForTimeout(400); }
}

// Сцены 1–10 (как в сценарии). prep — загрузка и вход в роль (в ролик не идёт), act — видимые действия:
// в ролик идут dur секунд от начала act; если действий меньше, остаток — медленный скролл.
// Только просмотр и черновики: приглашения не отправляются, потребности не сохраняются.
const ACTIONS = {
  1: { prep: async (p) => { await go(p, '/'); await cookies(p); } },
  2: { act: async (p) => { await show(p, 'Как это работает'); } },
  3: {
    prep: async (p) => { await role(p, 'Кандидат'); await go(p, '/candidate/assessment'); },
    act: async (p) => {
      await p.waitForTimeout(2500);
      const ok = p.locator('main label').filter({ hasText: 'даю согласие' }).first();
      if (await ok.count()) { await ok.scrollIntoViewIfNeeded().catch(() => {}); await ok.click({ timeout: 5000 }).catch(() => {}); await p.waitForTimeout(800); }
      await click(p, 'Начать тест', { exact: true, wait: 3000 });
      // экран согласия на наблюдение: для ролика — без камеры
      await click(p, 'Пройти без камеры', { exact: true, wait: 3500 });
      await hideGuide(p);
      await scroll(p, 500, 4000);
    },
  },
  4: { prep: async (p) => { await go(p, '/candidate/category'); }, act: async (p) => { await p.waitForTimeout(3000); await show(p, 'Паспорт грейда'); } },
  5: {
    prep: async (p) => { await role(p, 'Работодатель'); await go(p, '/employer/needs'); },
    act: async (p) => {
      await p.waitForTimeout(1500);
      const ta = p.locator('main textarea').first();
      if (await ta.count()) {
        await ta.scrollIntoViewIfNeeded().catch(() => {});
        await ta.click().catch(() => {});
        await ta.pressSequentially('Нужен бэкенд-разработчик на Python для платёжного сервиса: FastAPI, PostgreSQL, Kafka. Уровень — middle, удалённо.', { delay: 28 }).catch(() => {});
        await p.waitForTimeout(800);
      } else console.log('  нет поля текста потребности');
      await click(p, 'Разобрать требования', { exact: true, wait: 6000 });
    },
  },
  6: {
    prep: async (p) => {
      await go(p, '/employer/needs');
      const links = await p.$$eval('main a[href^="/employer/needs/"]', (e) => e.map((x) => [x.getAttribute('href'), x.innerText])).catch(() => []);
      const href = (links.find((l) => /платёж/i.test(l[1])) || links[0] || [])[0];
      if (href) await go(p, href);
    },
    act: async (p) => {
      await show(p, 'Кого пригласить первым');
      await p.waitForTimeout(2500);
      await click(p, 'Подробнее: тест, ФСП, все причины', { exact: true, wait: 4000 });
      // форма приглашения: вилка обязательна; не отправляем
      await click(p, 'Пригласить', { exact: true, wait: 4000 });
    },
  },
  7: {
    // паспорт ФСП кандидата: связь с ФСП ID, строки официальных протоколов, статус проверки
    prep: async (p) => { await role(p, 'Кандидат'); await go(p, '/candidate/fsp'); },
    act: async (p) => { await p.waitForTimeout(3000); },
  },
  8: { prep: async (p) => { await go(p, '/validation'); } },
  9: {
    prep: async (p) => {
      await go(p, '/api/docs');
      const ok = await p.locator('.opblock').first().waitFor({ timeout: 20000 }).then(() => true).catch(() => false);
      // запасной кадр: карта разделов ТЗ с интеграциями (если описание API не успело загрузиться)
      if (!ok) { console.log('  /api/docs не загрузилось — показываем /criteria'); await go(p, '/criteria'); await show(p, 'Интеграц'); }
    },
  },
  10: { prep: async (p) => { await go(p, '/'); }, act: async (p) => { await p.waitForTimeout(2000); await click(p, 'Демо для жюри', { exact: true, wait: 2500 }); } },
};

// Запись: встроенная запись видео браузера (кадры с метками времени страницы, без задержек приёма) → нарезка ffmpeg.
const RAW = path.join(OUT, 'raw');
fs.rmSync(RAW, { recursive: true, force: true });
const b = await chromium.launch({ args: ['--no-sandbox'], executablePath: process.env.CHROME || undefined });
const ctx = await b.newContext({ viewport: { width: W, height: H }, ignoreHTTPSErrors: true, locale: 'ru-RU',
  recordVideo: { dir: RAW, size: { width: W, height: H } } });
const p = await ctx.newPage();
const t0 = Date.now() / 1000; // начало записи ≈ создание страницы
await p.goto(ENTRY, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
const marks = [];
await cookies(p);
for (const s of scenes) {
  const a = ACTIONS[s.n] || {};
  const tp = Date.now() / 1000;
  if (a.prep) await a.prep(p);
  await hideGuide(p);
  console.log(`  сцена ${s.n}: подготовка ${(Date.now() / 1000 - tp).toFixed(1)} с, адрес ${new URL(p.url()).pathname}`);
  const start = Date.now() / 1000;
  if (a.act) await a.act(p);
  const left = s.dur - (Date.now() / 1000 - start);
  if (left > 0) await scroll(p, s.n === 1 ? 300 : 900, left * 1000);
  // в ролик — первые dur секунд от начала видимых действий
  marks.push({ ...s, a: start - t0, b: start - t0 + s.dur });
  console.log(`  сцена ${s.n}: действия ${(Date.now() / 1000 - start).toFixed(1)} с, в ролик — ${s.dur} с`);
}
const raw = await p.video().path();
await ctx.close();
await b.close();

// Нарезка: сцены подряд, титр сцены — на её отрезке.
const caps = [];
let tl = 0;
const parts = marks.map((m, i) => {
  caps.push({ title: m.title, a: tl, b: tl + m.dur });
  tl += m.dur;
  return `[0:v]trim=start=${m.a.toFixed(3)}:end=${m.b.toFixed(3)},setpts=PTS-STARTPTS[v${i}]`;
});
fs.writeFileSync(path.join(OUT, 'scenes.json'), JSON.stringify(caps, null, 1));
const esc = (t) => t.replace(/\\/g, '\\\\').replace(/:/g, '\\:').replace(/'/g, '’').replace(/%/g, '\\%').replace(/,/g, '\\,');
const font = process.env.CAPTION_FONT || '/usr/share/fonts/truetype/montserrat/Montserrat-SemiBold.ttf';
const fontArg = fs.existsSync(font) ? `fontfile='${font}':` : "font='Montserrat':";
const filters = caps.map((c) => `drawtext=${fontArg}text='${esc(c.title)}':x=48:y=h-96:fontsize=30:fontcolor=white:box=1:boxcolor=0x0A0B1F@0.78:boxborderw=18:enable='between(t,${c.a.toFixed(2)},${c.b.toFixed(2)})'`);
filters.push(`drawtext=${fontArg}text='Черновик · без голоса · fsp-draft.ru':x=w-tw-36:y=28:fontsize=18:fontcolor=white@0.85:box=1:boxcolor=0x402FFF@0.6:boxborderw=8`);
const out = path.join(OUT, 'draft_video.mp4');
const graph = parts.join(';') + ';' + marks.map((_, i) => `[v${i}]`).join('') + `concat=n=${marks.length}:v=1:a=0[cat];`
  + `[cat]fps=25,` + filters.join(',') + '[out]';
execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', raw, '-filter_complex', graph, '-map', '[out]',
  '-t', String(tl), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-an', out], { stdio: 'inherit' });
fs.rmSync(RAW, { recursive: true, force: true });
console.log('  записано', path.relative(process.cwd(), out), `(${tl} с)`);
