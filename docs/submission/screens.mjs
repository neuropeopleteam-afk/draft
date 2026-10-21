// Скриншоты наработок для организаторов (1920×1080, PNG) — с живого сайта, тем же входом, что у эксперта.
//   DRAFT_ENTRY="https://fsp-draft.ru/x/<токен>?next=/" node docs/submission/screens.mjs
// Результат: docs/submission/assets/screens/*.png (в git — только итоговые, выбранные штабом).
// Только просмотр: приглашения не отправляются, потребности не сохраняются.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../presentation/package.json'));
const { chromium } = require('playwright');
const ENTRY = process.env.DRAFT_ENTRY || 'https://fsp-draft.ru/';
const BASE = process.env.DRAFT_BASE || new URL(ENTRY).origin;
const OUT = process.env.SCREENS_OUT || path.join(HERE, 'assets', 'screens');
const ONLY = (process.env.SCREENS_ONLY || '').split(',').filter(Boolean);
fs.mkdirSync(OUT, { recursive: true });

async function settle(p, ms = 1500) {
  await p.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await p.waitForTimeout(ms);
}
async function go(p, url) {
  await p.goto(BASE + url, { waitUntil: 'load', timeout: 60000 }).catch((e) => console.log(`  ${url}: ${e.message.split('\n')[0]}`));
  await settle(p);
  await tidy(p);
}
async function tidy(p) {
  await p.getByRole('button', { name: 'Только необходимые' }).click({ timeout: 1500 }).catch(() => {});
  const b = p.getByRole('button', { name: 'Скрыть проводник', exact: true }).first();
  if (await b.count() && await b.isVisible().catch(() => false)) { await b.click({ timeout: 3000 }).catch(() => {}); await p.waitForTimeout(500); }
}
async function role(p, name) {
  await go(p, '/demo');
  const btn = p.locator('#jury-roles-anchor button').filter({ hasText: new RegExp(`^\\s*${name}\\s*$`) }).first();
  await btn.scrollIntoViewIfNeeded().catch(() => {});
  await btn.click({ timeout: 20000 }).catch((e) => console.log(`  роль «${name}»: ${e.message.split('\n')[0]}`));
  await settle(p, 2500);
}
async function scrollTo(p, text, top = 120) {
  const el = p.getByText(text).first();
  if (await el.count()) {
    await el.evaluate((n, t) => { const r = n.getBoundingClientRect(); window.scrollBy(0, r.top - t); }, top).catch(() => {});
    await p.waitForTimeout(800);
    return true;
  }
  console.log(`  нет на экране: «${text}»`);
  return false;
}

const SHOTS = {
  // 1. Главная — первый экран
  landing: async (p) => { await go(p, '/'); },
  // 2. Подборка работодателя: подтверждённый грейд, «почему в подборке», вилка в приглашении
  selection: async (p) => {
    await role(p, 'Работодатель');
    await go(p, '/employer/needs');
    const links = await p.$$eval('main a[href^="/employer/needs/"]', (e) => e.map((x) => [x.getAttribute('href'), x.innerText])).catch(() => []);
    const href = (links.find((l) => /платёж/i.test(l[1])) || links[0] || [])[0];
    if (href) await go(p, href); else console.log('  нет ссылок на подборки');
    await scrollTo(p, 'Версии подборки:', 46);
  },
  // 3. Итог теста кандидата: категория «направление · грейд» и паспорт грейда
  category: async (p) => { await role(p, 'Кандидат'); await go(p, '/candidate/category'); },
  // 4. Как мы проверяем себя: две колонки цифр с условиями
  validation: async (p) => { await go(p, '/validation'); },
  // 5. Паспорт ФСП кандидата: строки официальных протоколов
  fsp: async (p) => { await role(p, 'Кандидат'); await go(p, '/candidate/fsp'); },
};

const b = await chromium.launch({ args: ['--no-sandbox'] });
const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, ignoreHTTPSErrors: true, locale: 'ru-RU' });
const p = await ctx.newPage();
await p.goto(ENTRY, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
await tidy(p);
let i = 0;
for (const [name, fn] of Object.entries(SHOTS)) {
  i += 1;
  if (ONLY.length && !ONLY.includes(name)) continue;
  await fn(p);
  await tidy(p);
  await p.mouse.move(1900, 1070);
  const file = path.join(OUT, `Draft_${String(i).padStart(2, '0')}_${name}.png`);
  await p.screenshot({ path: file });
  console.log(`  ${path.relative(process.cwd(), file)} ← ${new URL(p.url()).pathname}`);
}
await b.close();
