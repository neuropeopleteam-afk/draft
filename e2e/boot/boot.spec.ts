/**
 * Я16: устойчивая загрузка — никаких белых экранов (playwright.boot.config.ts: собранный фронтенд + подмена /api).
 *
 * Сеть ломается через page.route так же, как у зарубежных соединений со стендом 10.10 (журнал nginx: «200» с
 * обрезанным телом 163–418 КБ, у облачных браузеров #root пуст, DOMContentLoaded не наступил):
 *   - основной файл завис / оборвался / пришёл обрезанным → сообщение (с подсказкой про VPN) и «Обновить»,
 *     одна автоматическая повторная загрузка (?r=метка), после неё приложение открылось, метка убрана из адреса;
 *   - второй сбой подряд → только кнопка, без цикла перезагрузок;
 *   - CSS завис → экран загрузки всё равно рисуется (стили сборки не блокируют первую отрисовку);
 *   - файл ленивого экрана оборвался → «Раздел не загрузился» → повторная загрузка → экран открылся;
 *   - 500/503/обрыв на /api/me, /api/meta → экран повтора, вход сохранён; «Повторить» → кабинет;
 *   - axe (WCAG 2.1 A/AA) на экранах сбоя, 390 и 1440 без горизонтальной прокрутки;
 *   - бюджет: стартовый JS ≤ 250 КБ gzip, index.html ≤ 12 КБ (сторож доходит целиком даже при обрыве ~16 КБ).
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { expect, test, type Page, type Route } from "@playwright/test";

const DIST = resolve(dirname(fileURLToPath(import.meta.url)), "../../frontend/dist");
const AXE_JS = process.env.AXE_JS || "/tmp/boot/axe.min.js";
const MAIN_JS = /\/assets\/index-[^/]+\.js$/;
const MAIN_CSS = /\/assets\/index-[^/]+\.css$/;

const META = {
  product_name: "Проверка", version: "e2e", jury_mode_available: true, demo_sandbox: true, assessment_engine: "irt",
  llm: { configured: false, provider: null, model: null }, operator: {}, proctor_camera: false,
  rules: { grade_change_interval_days: 30, retake_same_grade_days: 14, invitation_cooldown_days: 30 },
};
const ME = {
  id: "00000000-0000-0000-0000-000000000001", email: "candidate@example.test", role: "candidate", is_email_verified: true,
  created_at: "2026-10-01T10:00:00Z", employer: null, fsp: { linked: false, link_source: null, achievements_count: 0 },
  candidate: {
    full_name: "Кандидат (модель, не человек)", phone: null, telegram: null, city: "Москва", work_format: "remote", relocation: false,
    experience_years: 2, salary_min_hidden: null, current_category_id: null, current_grade_id: null, current_direction_id: null,
    rating_score: null, grade_locked_until: null, visible_to_employers: true, privacy: {}, public_ref: null,
    onboarding_completed_at: "2026-10-01T10:00:00Z", roles: ["candidate"], fsp_id_claimed: null, jury_mode: false,
    specializations: [], age_group: "adult", parental_consent: false, parental_consent_at: null,
  },
};

type Handler = (route: Route, url: URL) => Promise<unknown> | unknown;

/** Все /api/* — из теста: /meta — META, остальное — 404 (экраны это переживают), over — свои ответы по пути. */
async function mockApi(page: Page, over: Record<string, Handler | object> = {}) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname.replace(/^\/api/, "");
    const h = over[p];
    if (typeof h === "function") return (h as Handler)(route, url);
    if (h !== undefined) return route.fulfill({ json: h });
    if (p === "/meta") return route.fulfill({ json: META });
    return route.fulfill({ status: 404, json: { detail: "Not Found" } });
  });
}

/** Файл сборки: первые `bad` запросов ломаются способом how, дальше — как есть. Возвращает счётчик запросов. */
async function breakAsset(page: Page, re: RegExp, how: "hang" | "reset" | "cut", bad = 1) {
  const seen = { n: 0 };
  await page.route(re, async (route) => {
    seen.n++;
    if (seen.n > bad) return route.continue();
    if (how === "hang") return;  // ответа нет и не будет: соединение «висит», как у облачных браузеров 10.10
    if (how === "reset") return route.abort("connectionreset");
    const res = await route.fetch();
    const body = (await res.body()).subarray(0, 16 * 1024);  // обрыв на 16 КБ: тело неполное
    return route.fulfill({ status: 200, headers: { "content-type": "application/javascript" }, body });
  });
  return seen;
}

const appReady = (page: Page) => expect(page.locator("main#main").first()).toBeVisible();
const landing = (page: Page) => expect(page.locator('a[href="#main"]')).toHaveCount(1);  // SkipLink — приложение отрисовано

async function noHorizontalScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(sw, "горизонтальная прокрутка").toBeLessThanOrEqual(iw);
}

async function axe(page: Page, what: string) {
  if (!existsSync(AXE_JS)) { test.info().annotations.push({ type: "axe", description: `пропущено: нет ${AXE_JS}` }); return; }
  await page.addScriptTag({ path: AXE_JS });
  const res = await page.evaluate(async () => {
    const r = await (window as any).axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
    return r.violations.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
  });
  test.info().annotations.push({ type: "axe", description: `${what}: ${res.length ? JSON.stringify(res) : "0 замечаний"}` });
  expect(res, `axe: ${what}`).toEqual([]);
}

const desktopOnly = () => test.skip(test.info().project.name !== "desktop-1440", "сетевой сценарий — один раз, на 1440");

test("основной файл завис → сообщение, одна авто-повторная загрузка с ?r=, приложение открылось", async ({ page }) => {
  await mockApi(page);
  const main = await breakAsset(page, MAIN_JS, "hang");
  await page.goto("/", { waitUntil: "commit" });
  await expect(page.getByText("Загружаем…")).toBeVisible();
  const h = page.getByRole("heading", { level: 1, name: "Страница не загрузилась" });
  await expect(h).toBeVisible({ timeout: 12_000 });
  await expect(page.getByText("Если включён VPN — отключите его и обновите страницу.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Обновить" })).toBeVisible();
  await expect(page.getByText("Пробуем загрузить ещё раз…")).toBeVisible();
  await noHorizontalScroll(page);
  await axe(page, "сторож: страница не загрузилась");
  // повторная загрузка — сама, с меткой обхода кэша; после запуска метка убрана из адреса
  await page.waitForURL(/[?&]r=\d+/, { timeout: 10_000, waitUntil: "commit" });
  await landing(page);
  await appReady(page);
  expect(main.n).toBe(2);
  await expect.poll(() => new URL(page.url()).search).toBe("");
  await noHorizontalScroll(page);
});

test("обрыв соединения на основном файле → сообщение сразу, повтор успешен", async ({ page }) => {
  desktopOnly();
  await mockApi(page);
  const main = await breakAsset(page, MAIN_JS, "reset");
  const t0 = Date.now();
  await page.goto("/validation", { waitUntil: "commit" });
  await expect(page.getByRole("heading", { level: 1, name: "Страница не загрузилась" })).toBeVisible({ timeout: 8_000 });
  expect(Date.now() - t0, "без ожидания 9 с").toBeLessThan(8_000);
  await landing(page);
  expect(main.n).toBe(2);
  expect(new URL(page.url()).pathname).toBe("/validation");
});

test("основной файл пришёл обрезанным (16 КБ) → сообщение, повтор успешен", async ({ page }) => {
  desktopOnly();
  await mockApi(page);
  const main = await breakAsset(page, MAIN_JS, "cut");
  await page.goto("/", { waitUntil: "commit" });
  await expect(page.getByRole("heading", { level: 1, name: "Страница не загрузилась" })).toBeVisible({ timeout: 8_000 });
  await landing(page);
  expect(main.n).toBe(2);
});

test("второй сбой подряд — без цикла: только кнопка «Обновить»; по кнопке — открылось", async ({ page }) => {
  desktopOnly();
  await mockApi(page);
  const main = await breakAsset(page, MAIN_JS, "hang", 2);
  await page.goto("/", { waitUntil: "commit" });
  await page.waitForURL(/[?&]r=\d+/, { timeout: 15_000, waitUntil: "commit" });
  const h = page.getByRole("heading", { level: 1, name: "Страница не загрузилась" });
  await expect(h).toBeVisible({ timeout: 12_000 });
  await expect(page.getByText("Пробуем загрузить ещё раз…")).toHaveCount(0);
  await page.waitForTimeout(4_000);
  expect(main.n, "третьей автоматической загрузки нет").toBe(2);
  await page.getByRole("button", { name: "Обновить" }).click();
  await landing(page);
  expect(main.n).toBe(3);
});

test("CSS завис → экран загрузки всё равно рисуется (стили сборки не блокируют отрисовку)", async ({ page }) => {
  desktopOnly();
  await mockApi(page);
  const css = await breakAsset(page, MAIN_CSS, "hang");
  await page.goto("/", { waitUntil: "commit" });
  await page.waitForSelector("#boot", { state: "attached" });
  // кадр отрисовки наступает (requestAnimationFrame) — документ не заблокирован стилями из <head>
  const painted = await page.evaluate(() => new Promise<boolean>((r) => { requestAnimationFrame(() => r(true)); setTimeout(() => r(false), 3000); }));
  expect(painted, "первая отрисовка не ждёт CSS").toBe(true);
  await expect(page.getByRole("heading", { level: 1, name: "Страница не загрузилась" })).toBeVisible({ timeout: 12_000 });
  await landing(page);
  expect(css.n).toBe(2);
});

test("файл ленивого экрана оборвался → «Раздел не загрузился» → повторная загрузка → экран открылся", async ({ page }) => {
  desktopOnly();
  await mockApi(page);
  const chunk = await breakAsset(page, /\/assets\/Validation-[^/]+\.js$/, "reset");
  await page.goto("/validation", { waitUntil: "commit" });
  await expect(page.getByRole("heading", { level: 1, name: "Раздел не загрузился" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Обновить" })).toBeVisible();
  await axe(page, "раздел не загрузился");
  await page.waitForURL(/[?&]r=\d+/, { timeout: 10_000, waitUntil: "commit" });
  await expect(page.getByRole("heading", { level: 1, name: "Раздел не загрузился" })).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator("main h1").first()).toBeVisible();
  expect(chunk.n).toBe(2);
});

test("500 на /api/me → экран повтора, вход сохранён; «Повторить» → кабинет", async ({ page }) => {
  let meStatus = 500;
  await mockApi(page, { "/me": (route: Route) => meStatus === 200 ? route.fulfill({ json: ME }) : route.fulfill({ status: meStatus, json: { detail: "Internal Server Error" } }) });
  await page.addInitScript(() => { if (!localStorage.getItem("fsp_token")) localStorage.setItem("fsp_token", "e2e-token"); });
  await page.goto("/candidate");
  await expect(page.getByRole("heading", { level: 1, name: "Сервер временно не отвечает" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("fsp_token")), "вход не сброшен").toBe("e2e-token");
  expect(new URL(page.url()).pathname, "не уводит на /login").toBe("/candidate");
  await noHorizontalScroll(page);
  await axe(page, "сервер временно не отвечает");
  meStatus = 200;
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(page.getByRole("navigation", { name: "Кабинет кандидата" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Сервер временно не отвечает" })).toHaveCount(0);
  await noHorizontalScroll(page);
});

test("503 и обрыв сети на старте: главная не пустая, кабинет — экран повтора, повтор сам", async ({ page }) => {
  desktopOnly();
  let meCalls = 0;
  await mockApi(page, {
    "/meta": (route: Route) => route.fulfill({ status: 503, json: { detail: "Service Unavailable" } }),
    "/me": (route: Route) => { meCalls++; return meCalls <= 3 ? route.abort("connectionreset") : route.fulfill({ json: ME }); },
  });
  await page.addInitScript(() => { if (!localStorage.getItem("fsp_token")) localStorage.setItem("fsp_token", "e2e-token"); });
  await page.goto("/");
  await landing(page);
  await expect(page.locator("main#main h1").first()).toBeVisible();
  await page.goto("/candidate");
  await expect(page.getByRole("heading", { level: 1, name: "Сервер временно не отвечает" })).toBeVisible();
  await expect(page.getByText(/Повторим сами через \d+ с/)).toBeVisible();
  // через 10 с — повтор без нажатия: сеть вернулась — кабинет
  await expect(page.getByRole("navigation", { name: "Кабинет кандидата" })).toBeVisible({ timeout: 15_000 });
});

test("бюджет: стартовый JS ≤ 250 КБ gzip, index.html ≤ 12 КБ, рядом .gz и .br", async () => {
  desktopOnly();
  const html = readFileSync(resolve(DIST, "index.html"), "utf8");
  expect(Buffer.byteLength(html), "index.html (сторож доходит целиком даже при обрыве ~16 КБ)").toBeLessThanOrEqual(12 * 1024);
  const start = [...html.matchAll(/<(?:script type="module"[^>]*src|link rel="modulepreload"[^>]*href)="(\/assets\/[^"]+\.js)"/g)].map((m) => m[1]);
  expect(start.length, "основной файл и vendor").toBeGreaterThanOrEqual(2);
  let gz = 0;
  const rows: string[] = [];
  for (const f of start) {
    const raw = readFileSync(resolve(DIST, `.${f}`));
    const z = gzipSync(raw, { level: 9 }).length;
    gz += z;
    rows.push(`${f}: ${raw.length} Б, gzip ${z} Б`);
    expect(existsSync(resolve(DIST, `.${f}.gz`)), `${f}.gz`).toBe(true);
    expect(existsSync(resolve(DIST, `.${f}.br`)), `${f}.br`).toBe(true);
  }
  test.info().annotations.push({ type: "размеры", description: `${rows.join("; ")}; итого gzip ${gz} Б` });
  expect(gz, "стартовый JS, gzip").toBeLessThanOrEqual(250 * 1024);
  // стили сборки — в <body> после #root, не в <head>
  const head = html.slice(0, html.indexOf("</head>"));
  expect(head).not.toMatch(/rel="stylesheet"/);
  expect(html).toMatch(/<\/main><\/div>\s*<link rel="stylesheet"/);
});
