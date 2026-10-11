/**
 * «Надиктовать» потребность — только когда на стенде включён VOICE_NEED_ENABLED (по умолчанию выкл., тогда тесты
 * пропускаются). Проверяется на заглушке распознавания (INTERVIEW_STUB=1 или нет DEEPGRAM_API_KEY): сервер отвечает
 * фиксированным текстом примера, запись идёт с фальшивого микрофона Chromium (тон 440 Гц).
 *  1. 1440 px: «Надиктовать» → согласие → запись с индикатором и «Стоп» → текст в поле (можно поправить) → ничего не
 *     разобрано и не сохранено само → правка → «Разобрать требования» → прежний разбор с цитатами.
 *  2. 390 px: тот же путь без горизонтальной прокрутки, снимки.
 *  3. Отказ микрофона, браузер без записи, сбой распознавания (503) — понятное сообщение и «Ввести текстом» (фокус в поле).
 * axe-core (E2E_AXE=<путь к axe.min.js>): нарушений serious/critical нет. Без E2E_AXE проверка пропускается.
 */
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { apiContext } from "../lib/stand";
import { juryEnter, openSection } from "../lib/ui";

test.describe.configure({ mode: "serial" });
test.use({ launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] }, permissions: ["microphone"] });

const SHOTS = process.env.E2E_SHOTS_DIR || resolve(process.cwd(), "reports/mobile");
const AXE = process.env.E2E_AXE;
let voice: { enabled: boolean; stub?: boolean; max_seconds: number } | null = null;

async function noHScroll(page: Page, what: string) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w, `${what}: горизонтальная прокрутка`).toBeLessThanOrEqual(1);
}

async function axe(page: Page, what: string) {
  if (!AXE) return;
  await page.addScriptTag({ path: AXE });
  const bad = await page.evaluate(async () => {
    // @ts-expect-error axe подключён в страницу
    const r = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
    return r.violations.filter((v: any) => v.impact === "serious" || v.impact === "critical")
      .map((v: any) => `${v.id}: ${v.nodes.slice(0, 2).map((n: any) => n.target.join(" ")).join(" | ")}`);
  });
  expect(bad, `${what}: axe serious/critical`).toEqual([]);
}

/** «Надиктовать»: согласие спрашивается один раз за вкладку — нажать «Согласен», если оно показано. */
async function startDictation(block: ReturnType<Page["getByTestId"]>) {
  await block.getByRole("button", { name: "Надиктовать" }).click();
  const ok = block.getByRole("button", { name: "Согласен, включить микрофон" });
  const busy = block.getByTestId("voice-recording").or(block.getByTestId("voice-error"));
  await expect(ok.or(busy)).toBeVisible({ timeout: 20_000 });
  if (await ok.isVisible()) await ok.click();
}

async function needsPage(page: Page) {
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  const main = page.getByRole("main");
  return { main, field: main.getByRole("textbox", { name: "Кого вы ищете" }), block: main.getByTestId("voice-need") };
}

/** Надиктовать на фальшивый микрофон ~2 с и дождаться текста в поле. */
async function dictate(page: Page, block: ReturnType<Page["getByTestId"]>, field: ReturnType<Page["getByRole"]>, what: string) {
  await block.getByRole("button", { name: "Надиктовать" }).click();
  const consent = block.getByTestId("voice-consent");
  await expect(consent).toBeVisible();
  await expect(consent).toContainText("не сохраняются");
  await axe(page, `${what}: согласие`);
  await consent.getByRole("button", { name: "Согласен, включить микрофон" }).click();
  const rec = block.getByTestId("voice-recording");
  await expect(rec).toContainText(/Идёт запись · 0:0\d из 1:00/, { timeout: 20_000 });
  await expect(block.getByRole("button", { name: "Стоп" })).toBeVisible();
  await page.waitForTimeout(2200);
  await axe(page, `${what}: идёт запись`);
  const sent = page.waitForResponse((r) => r.url().includes("/api/employer/needs/voice") && r.request().method() === "POST");
  await block.getByRole("button", { name: "Стоп" }).click();
  const resp = await sent;
  expect(resp.status(), "распознавание ответило").toBe(200);
  const body = await resp.json();
  await expect(field).toHaveValue(body.text);
  await expect(block.getByTestId("voice-note")).toContainText("Разбор начнётся по кнопке «Разобрать требования»");
  await expect(field).toBeFocused();
  return body as { text: string; stub: boolean };
}

test.beforeAll(async () => {
  const api = await apiContext();
  try {
    const meta = await (await api.get("/api/meta")).json();
    voice = meta.voice_need?.enabled ? meta.voice_need : null;
  } finally {
    await api.dispose();
  }
});

test("1440: надиктовать → текст в поле → правка → прежний разбор; само ничего не разбирается", async ({ page }) => {
  test.skip(!voice, "VOICE_NEED_ENABLED выключен на стенде");
  await page.setViewportSize({ width: 1440, height: 900 });
  const { main, field, block } = await needsPage(page);
  await expect(block.getByText(/До 60 с голосом/)).toBeVisible();
  let parses = 0;
  page.on("request", (r) => { if (r.url().includes("/api/employer/needs/parse") && r.method() === "POST") parses += 1; });
  const out = await dictate(page, block, field, "1440");
  if (voice?.stub) {
    expect(out.stub).toBe(true);
    await expect(block.getByTestId("voice-note")).toContainText("Заглушка");
  }
  await test.step("ничего не разобрано и не сохранено само", async () => {
    await page.waitForTimeout(800);
    expect(parses, "разбор не запускается сам").toBe(0);
    await expect(main.getByRole("heading", { name: "Откуда взяты требования" })).toHaveCount(0);
  });
  await test.step("правка расшифровки и прежний разбор с цитатами", async () => {
    await field.press("End");
    await field.pressSequentially(" Будет плюсом Kafka.");
    await expect(field).toHaveValue(/Kafka\.$/);
    await main.getByRole("button", { name: "Разобрать требования" }).click();
    await expect(main.getByRole("heading", { name: "Откуда взяты требования" })).toBeVisible({ timeout: 60_000 });
    await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible();
    expect(parses).toBe(1);
    if (voice?.stub) await expect(main.locator("mark").filter({ hasText: "FastAPI" }).first()).toBeVisible();
  });
  await noHScroll(page, "1440");
  await axe(page, "1440: после разбора");
});

test("390: тот же путь без горизонтальной прокрутки, снимки", async ({ page }) => {
  test.skip(!voice, "VOICE_NEED_ENABLED выключен на стенде");
  await page.setViewportSize({ width: 390, height: 844 });
  const { field, block } = await needsPage(page);
  mkdirSync(SHOTS, { recursive: true });
  await noHScroll(page, "390: до записи");
  await block.getByRole("button", { name: "Надиктовать" }).click();
  await expect(block.getByTestId("voice-consent")).toBeVisible();
  await noHScroll(page, "390: согласие");
  await block.screenshot({ path: resolve(SHOTS, "17-voice-consent-390.png") });
  await block.getByRole("button", { name: "Согласен, включить микрофон" }).click();
  await expect(block.getByTestId("voice-recording")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(1500);
  await noHScroll(page, "390: запись");
  await block.screenshot({ path: resolve(SHOTS, "17-voice-recording-390.png") });
  await block.getByRole("button", { name: "Стоп" }).click();
  await expect(block.getByTestId("voice-note")).toBeVisible({ timeout: 30_000 });
  await expect(field).not.toHaveValue("");
  await noHScroll(page, "390: текст в поле");
  await axe(page, "390: текст в поле");
  await page.getByRole("main").screenshot({ path: resolve(SHOTS, "17-voice-text-390.png") });
});

test("сбои: отказ микрофона, браузер без записи, распознавание недоступно — сообщение и клавиатура", async ({ page }) => {
  test.skip(!voice, "VOICE_NEED_ENABLED выключен на стенде");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    const mode = localStorage.getItem("e2e_voice_mode");
    if (mode === "denied") navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
    if (mode === "nomic") navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Requested device not found", "NotFoundError"));
    if (mode === "unsupported") (window as any).MediaRecorder = undefined;
  });
  const { field, block } = await needsPage(page);
  const err = block.getByTestId("voice-error");
  for (const [mode, re] of [["denied", /Доступ к микрофону не разрешён/], ["nomic", /Микрофон не найден/], ["unsupported", /не умеет записывать звук/]] as const) {
    await test.step(mode, async () => {
      await page.evaluate((m) => localStorage.setItem("e2e_voice_mode", m), mode);
      await page.reload({ waitUntil: "domcontentloaded" });
      await startDictation(block);
      await expect(err).toContainText(re);
      await expect(err).toContainText("введите текст с клавиатуры");
      await err.getByRole("button", { name: "Ввести текстом" }).click();
      await expect(field).toBeFocused();
      await expect(err).toHaveCount(0);
    });
  }
  await test.step("распознавание недоступно (503) — текст сервера и клавиатура", async () => {
    await page.evaluate(() => localStorage.removeItem("e2e_voice_mode"));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.route("**/api/employer/needs/voice**", (r) => r.fulfill({ status: 503, contentType: "application/json",
      body: JSON.stringify({ detail: { code: "voice_unavailable", message: "Распознавание речи недоступно — введите текст с клавиатуры" } }) }));
    await startDictation(block);
    await expect(block.getByTestId("voice-recording")).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(1200);
    await block.getByRole("button", { name: "Стоп" }).click();
    await expect(err).toContainText("Распознавание речи недоступно — введите текст с клавиатуры");
    await expect(field).toHaveValue("");
    await axe(page, "сбой распознавания");
    await field.fill("Ищем аналитика данных: SQL и Python");
    await expect(page.getByRole("main").getByRole("button", { name: "Разобрать требования" })).toBeEnabled();
  });
});
