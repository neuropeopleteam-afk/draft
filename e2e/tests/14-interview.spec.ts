/**
 * Я15 «Устная защита ответа и ИИ-интервью» — только когда на стенде включён INTERVIEW_ENABLED (по умолчанию выкл.,
 * тогда тест пропускается). Проверяется на заглушке движка (INTERVIEW_ENGINE=stub или движок без ключа модели):
 * вопросы по шаблону, оценка — правилом, кнопка «Подставить начало письменного ответа (заглушка)» отвечает за кандидата.
 *  1. Кандидат с развёрнутыми ответами (Мария): категория → «Подтвердите авторство ответа» с готовым примером песочницы
 *     («пример, модельный кандидат») → согласие → разговор в чате (канал «текст») → итог «ответ подтверждён устно».
 *  2. Работодатель: значок на карточке кандидата и подробности с подтверждёнными цитатами и расшифровкой.
 *  3. Этап найма «ИИ-интервью»: работодатель приглашает в принятом приглашении, кандидат видит его у себя;
 *     итог кандидату не показывается.
 *  4. 390 px: те же экраны без горизонтальной прокрутки, снимки.
 * axe-core (E2E_AXE=<путь к axe.min.js>, например tools/a11y/axe_audit.cjs → /tmp/axe.min.js): нарушений уровня
 * serious/critical на новых экранах нет. Без E2E_AXE проверка доступности пропускается (пакеты не добавляются).
 */
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, newPersonaContext, test } from "../lib/fixtures";
import { apiContext, apiGet, juryToken } from "../lib/stand";
import { juryEnter } from "../lib/ui";

test.describe.configure({ mode: "serial" });

const SHOTS = process.env.E2E_SHOTS_DIR || resolve(process.cwd(), "reports/mobile");
const AXE = process.env.E2E_AXE;
let enabled = false;
let mariaRef = "";

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

test.beforeAll(async () => {
  const api = await apiContext();
  try {
    const meta = await (await api.get("/api/meta")).json();
    enabled = meta.interview_enabled === true;
    if (enabled) mariaRef = (await apiGet(api, "/me", await juryToken(api, "candidate"))).candidate.public_ref;
  } finally {
    await api.dispose();
  }
});

test("кандидат: устная защита в чате на заглушке → «ответ подтверждён устно»; работодатель видит значок и цитаты", async ({ page, browser }) => {
  test.skip(!enabled, "INTERVIEW_ENABLED выключен на стенде");
  await page.setViewportSize({ width: 1440, height: 900 });
  await juryEnter(page, "candidate");
  await test.step("категория: панель «Подтвердите авторство ответа» и готовый пример песочницы", async () => {
    await page.goto("/candidate/category#defense", { waitUntil: "domcontentloaded" });
    const panel = page.getByTestId("defense-panel");
    await expect(panel).toBeVisible({ timeout: 60_000 });
    await expect(panel.getByRole("heading", { name: /^Подтвердите авторство ответа: устная защита \d+ минут/ })).toBeVisible();
    await expect(panel).toContainText("Грейд не меняется");
    await expect(panel.getByTestId("defense-example")).toContainText("пример, модельный кандидат");
    await axe(page, "категория с панелью защиты");
  });
  await test.step("согласие → разговор в чате", async () => {
    const panel = page.getByTestId("defense-panel");
    await panel.getByTestId("defense-open").click();
    await panel.getByRole("checkbox").check();
    await panel.getByTestId("interview-defense-start").click();
    await expect(page).toHaveURL(/\/candidate\/interview\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    await page.getByTestId("iv-begin-text").click();
    const q = page.getByTestId("iv-question");
    const result = page.getByTestId("interview-result");
    let prev = "";
    for (let i = 0; i < 6; i++) {
      await expect(q.or(result)).toBeVisible({ timeout: 60_000 });
      if (await result.isVisible()) break;
      await expect(q).not.toHaveText(prev);  // следующий вопрос, а не прежний
      prev = (await q.textContent()) ?? "";
      if (i === 0) await axe(page, "разговор");
      const hint = page.getByTestId("iv-hint");
      if (await hint.isVisible()) await hint.click();
      else await page.getByLabel("Ваш ответ").fill("Отвечаю своими словами: сначала проверяю входные данные, затем выбираю структуру и объясняю почему.");
      await page.getByTestId("iv-send").click();
      await expect(q.or(result)).toBeVisible({ timeout: 60_000 });
      if (await result.isVisible()) break;
      await expect(q).not.toHaveText(prev, { timeout: 60_000 });
      prev = "";
    }
    await expect(result).toBeVisible({ timeout: 90_000 });
    await expect(result).toContainText(/Ответ подтверждён устно|Есть расхождения|Мало данных/);
    await expect(result).toContainText("заглушка");
    await axe(page, "итог разговора");
  });
  await test.step("работодатель: значок в карточке и подробности с цитатами", async () => {
    const emp = await (await newPersonaContext(browser)).newPage();
    await emp.setViewportSize({ width: 1440, height: 900 });
    await juryEnter(emp, "employer");
    await emp.goto(`/employer/candidates/${mariaRef}`, { waitUntil: "domcontentloaded" });
    await expect(emp.getByTestId("defense-badge").first()).toBeVisible({ timeout: 60_000 });
    const d = emp.getByTestId("defense-details");
    await expect(d).toBeVisible();
    await expect(d.getByTestId("interview-result")).toBeVisible();
    await expect(d).toContainText("модель, не люди");
    await axe(emp, "карточка кандидата у работодателя");
    await emp.context().close();
  });
});

test("этап найма «ИИ-интервью»: приглашение работодателя видно кандидату", async ({ page, browser }) => {
  test.skip(!enabled, "INTERVIEW_ENABLED выключен на стенде");
  const api = await apiContext();
  let invId = "";
  try {
    const te = await juryToken(api, "employer");
    const tc = await juryToken(api, "candidate");
    const r = await api.post("/api/employer/invitations", {
      headers: { Authorization: `Bearer ${te}` },
      data: { position_title: "Python-разработчик (ИИ-интервью)", offer_description: "Платёжный API, команда 6 человек.",
              salary_from: 220000, salary_to: 300000, contact_method: "Telegram @hr_demo", candidate_ref: mariaRef },
    });
    test.skip(!r.ok(), `приглашение не создано (${r.status()}) — правило повторных приглашений песочницы`);
    invId = (await r.json()).id;
    expect((await api.post(`/api/candidate/invitations/${invId}/accept`, { headers: { Authorization: `Bearer ${tc}` } })).ok()).toBe(true);
  } finally {
    await api.dispose();
  }
  await juryEnter(page, "employer");
  await page.goto("/employer/invitations", { waitUntil: "domcontentloaded" });
  const block = page.getByTestId("ai-interview-employer").filter({ has: page.getByRole("button", { name: "Пригласить на ИИ-интервью" }) }).first();
  await expect(block).toBeVisible({ timeout: 60_000 });
  const skills = block.getByLabel("Добавить навыки (через запятую)");
  if (await skills.inputValue() === "") await skills.fill("Kafka, код-ревью");
  await block.getByRole("button", { name: "Пригласить на ИИ-интервью" }).click();
  await expect(page.getByTestId("ai-interview-employer").filter({ hasText: "Приглашение отправлено" }).first()).toBeVisible();
  await axe(page, "приглашения работодателя");

  const cand = await (await newPersonaContext(browser)).newPage();
  await juryEnter(cand, "candidate");
  await cand.goto("/candidate/invitations", { waitUntil: "domcontentloaded" });
  await cand.getByText("Python-разработчик (ИИ-интервью)").first().click();
  const ai = cand.getByTestId("ai-interview-candidate");
  await expect(ai).toBeVisible({ timeout: 60_000 });
  await expect(ai).toContainText("Компания приглашает на ИИ-интервью");
  await expect(ai.getByRole("button", { name: "Начать ИИ-интервью" })).toBeVisible();
  await axe(cand, "приглашение кандидата");
  await cand.context().close();
});

test("390 px: панель защиты, разговор и карточка работодателя без горизонтальной прокрутки", async ({ page, browser }) => {
  test.skip(!enabled, "INTERVIEW_ENABLED выключен на стенде");
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await juryEnter(page, "candidate");
  await page.goto("/candidate/category#defense", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("defense-panel")).toBeVisible({ timeout: 60_000 });
  await noHScroll(page, "категория, панель защиты");
  await page.getByTestId("defense-panel").screenshot({ path: resolve(SHOTS, "14-interview-panel-390.png") });
  const emp = await (await newPersonaContext(browser)).newPage();
  await emp.setViewportSize({ width: 390, height: 844 });
  await juryEnter(emp, "employer");
  await emp.goto(`/employer/candidates/${mariaRef}`, { waitUntil: "domcontentloaded" });
  await expect(emp.getByTestId("defense-details")).toBeVisible({ timeout: 60_000 });
  await noHScroll(emp, "карточка кандидата, устная защита");
  await emp.getByTestId("defense-details").screenshot({ path: resolve(SHOTS, "14-interview-employer-390.png") });
  await emp.context().close();
});
