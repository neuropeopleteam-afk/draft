/**
 * Я16: устойчивая загрузка интерфейса — отдельный набор e2e без backend и без стенда.
 *
 * Собранный фронтенд (frontend/dist, `npm run build`) раздаёт `vite preview`; все запросы /api/* подменяются в тесте
 * (page.route), сеть до файлов сборки ломается так же через route: зависание основного файла, обрыв соединения,
 * обрезанное тело (как обрывы ~16 КБ у зарубежных соединений со стендом 10.10), 500/503 и обрыв сети на /api/me.
 *
 *   cd frontend && npm run build
 *   cd ../e2e && npx playwright test -c playwright.boot.config.ts
 *
 * Переменные: E2E_BOOT_PORT (по умолчанию 5716), AXE_JS — путь к axe.min.js (axe-core 4.x) для проверки
 * доступности экранов загрузки (нет файла — проверка axe пропускается с пометкой в отчёте).
 */
import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_BOOT_PORT || 5716);

export default defineConfig({
  testDir: "./boot",
  outputDir: "reports/boot-artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["json", { outputFile: "reports/boot-results.json" }]],
  webServer: {
    command: `npx vite preview --host 127.0.0.1 --port ${port} --strictPort`,
    cwd: "../frontend",
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // service worker не нужен: подмена сети через page.route его запросы не видит
    serviceWorkers: "block",
    locale: "ru-RU",
    timezoneId: "Europe/Moscow",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "phone-390", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: false, hasTouch: true } },
  ],
});
