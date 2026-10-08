/**
 * Сквозные тесты сценария жюри (Playwright, Chromium).
 *
 * Куда идут запросы — только из переменных окружения:
 *   E2E_BASE_URL        адрес стенда или локального стека (по умолчанию http://127.0.0.1:8140 — `make up`)
 *   E2E_BASIC_USER      базовая авторизация nginx стенда (на стенде fsp.neuropeople.pro — demo)
 *   E2E_BASIC_PASSWORD  пароль базовой авторизации (выдаётся с материалами сдачи, в репозитории его нет)
 *   E2E_SCENARIO=<id>   продолжить свою песочницу жюри (по умолчанию global-setup создаёт новую)
 *   E2E_KEEP_STATE=1    не сбрасывать песочницу после прогона (для разбора упавшего теста)
 *   E2E_STRICT=1        известные ошибки продукта (productIssue) валят тест, а не только отмечаются
 *   E2E_SHOTS_DIR       куда класть снимки экранов 390 px (по умолчанию reports/mobile)
 *
 * Один прогон = одна песочница жюри (вход с scenario "new"): все демо-персоны прогона — её учётки, браузер
 * получает её id в localStorage, как у эксперта жюри. В конце сбрасывается только она; общее демо и
 * песочницы других экспертов жюри тесты не трогают. Внутри песочницы тесты меняют состояние (тест, потребности,
 * приглашения, жалоба, кубок, разметка), поэтому идут строго по очереди в одном потоке.
 */
import { defineConfig, devices } from "@playwright/test";
import { NET_RETRY } from "./lib/net";

const baseURL = (process.env.E2E_BASE_URL || "http://127.0.0.1:8140").replace(/\/$/, "");
const user = process.env.E2E_BASIC_USER;
const password = process.env.E2E_BASIC_PASSWORD;

export default defineConfig({
  testDir: "./tests",
  outputDir: "reports/artifacts",
  fullyParallel: false,
  workers: 1,
  // Повтор упавшего шага сценария на живом стенде не имеет смысла: состояние уже изменено (лимит 30 дней).
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 8 * 60_000,
  // удалённый стенд: GET могут повторяться (lib/net.ts), поэтому ожидания длиннее, чем для локального стека
  expect: { timeout: NET_RETRY ? 60_000 : 20_000 },
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  reporter: [
    ["list"],
    ["html", { outputFolder: "reports/html", open: "never" }],
    ["junit", { outputFile: "reports/junit.xml" }],
    ["json", { outputFile: "reports/results.json" }],
  ],
  use: {
    baseURL,
    httpCredentials: user && password ? { username: user, password, origin: new URL(baseURL).origin } : undefined,
    // service worker PWA не нужен тестам и уводил бы запросы мимо повтора GET (lib/net.ts)
    serviceWorkers: "block",
    locale: "ru-RU",
    timezoneId: "Europe/Moscow",
    actionTimeout: NET_RETRY ? 60_000 : 20_000,
    navigationTimeout: NET_RETRY ? 150_000 : 45_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } } },
  ],
});
