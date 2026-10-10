/**
 * hh.ru (Я12, docs/INTEGRATIONS.md): импорт своей вакансии в черновик и «Рынок по hh.ru» у вилки приглашения.
 *
 * Только на стенде с HH_ENABLED=1 и заглушкой HH_STUB=1 (фикстуры modules/hh/fixtures, данные не настоящие); без
 * включённой интеграции спек пропускается. Работодатель песочницы жюри («Северный платёж»): «Вакансии» →
 * «Импортировать с hh.ru» → номер 90000001 → предпросмотр → черновик с пометкой «с hh.ru · № …»; чужая вакансия
 * 90000003 — только с флажком «Это вакансия нашей компании»; приглашение кандидату → строка «Рынок по hh.ru».
 * 1440 и 390 px без горизонтальной прокрутки; axe (WCAG 2.1 A/AA) на окне импорта и форме приглашения — если задан
 * E2E_AXE (путь к axe.min.js, как у tools/a11y/axe_audit.cjs). Снимки — в E2E_SHOTS_DIR/hh.
 */
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { apiContext, apiGet, juryToken } from "../lib/stand";
import { juryEnter, openSection } from "../lib/ui";

const DIR = join(process.env.E2E_SHOTS_DIR || "reports", "hh");
mkdirSync(DIR, { recursive: true });
const AXE = process.env.E2E_AXE || "";

async function shot(page: Page, name: string): Promise<void> {
  const file = join(DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}
const noHScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

/** axe-core по контейнеру: нарушений critical/serious нет (остальные — в отчёт). */
async function axe(page: Page, scope: string, label: string): Promise<void> {
  if (!AXE || !existsSync(AXE)) { test.info().annotations.push({ type: "axe", description: "E2E_AXE не задан — пропущено" }); return; }
  if (!(await page.evaluate(() => "axe" in window))) await page.addScriptTag({ path: AXE });
  const res = await page.evaluate(async (sel) => {
    // @ts-expect-error axe — глобальный объект из axe.min.js
    const r = await window.axe.run(sel, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
    return r.violations.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
  }, scope);
  test.info().annotations.push({ type: "axe", description: `${label}: ${JSON.stringify(res)}` });
  expect(res.filter((v: any) => v.impact === "critical" || v.impact === "serious"), `axe ${label}`).toEqual([]);
}

test.describe.configure({ mode: "serial" });

test("hh.ru: своя вакансия → черновик; чужая — с подтверждением; «Рынок по hh.ru» у вилки", async ({ page }) => {
  const api = await apiContext();
  const meta = await (await api.get("/api/meta")).json();
  test.skip(!meta.hh?.enabled, "интеграция hh.ru выключена (HH_ENABLED)");
  await juryEnter(page, "employer");
  const dialog = page.getByRole("dialog", { name: "Импорт своей вакансии с hh.ru" });
  const open = async () => {
    await page.getByRole("button", { name: "Импортировать с hh.ru" }).click();
    await expect(dialog).toBeVisible();
  };
  const preview = async (ref: string): Promise<Locator> => {
    await dialog.getByRole("textbox", { name: "Ссылка или номер вакансии" }).fill(ref);
    await dialog.getByRole("button", { name: "Показать" }).click();
    const p = dialog.getByTestId("hh-preview");
    await expect(p).toBeVisible({ timeout: 30_000 });
    return p;
  };

  await test.step("1440: «Вакансии» → кнопка рядом с «Импортировать из ATS» → предпросмотр своей вакансии", async () => {
    await openSection(page, "Вакансии", /\/employer\/vacancies$/);
    await expect(page.getByRole("button", { name: "Импортировать из ATS" })).toBeVisible();
    await open();
    if (meta.hh?.stub) await expect(dialog.getByText(/заглушка hh\.ru \(данные не настоящие\)/)).toBeVisible();
    const p = await preview("https://hh.ru/vacancy/90000001?from=share");
    await expect(p).toContainText("Middle Python-разработчик");
    await expect(p).toContainText("совпадает с вашей компанией");
    await expect(p).toContainText("Backend · Middle");
    await expect(p.getByRole("link", { name: /открыть на hh\.ru/ })).toHaveAttribute("href", /hh\.ru\/vacancy\/90000001/);
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "import-preview-1440");
    await axe(page, '[role="dialog"]', "окно импорта 1440");
  });

  await test.step("черновик с пометкой «с hh.ru», повторный импорт — «без изменений»", async () => {
    await dialog.getByRole("button", { name: "Создать черновик" }).click();
    await expect(dialog.getByRole("status").filter({ hasText: "Черновик — в списке вакансий" })).toBeVisible();
    await dialog.getByRole("button", { name: "Закрыть" }).first().click();
    const row = page.getByRole("listitem").filter({ hasText: "Middle Python-разработчик" }).first();
    await expect(row).toContainText("Черновик");
    await expect(row.getByRole("link", { name: /с hh\.ru · № 90000001/ })).toBeVisible();
    await open();
    const p = await preview("90000001");
    await expect(p).toContainText("без изменений");
    await expect(dialog.getByRole("button", { name: "Создать черновик" })).toBeDisabled();
    await dialog.getByRole("button", { name: "Закрыть" }).first().click();
  });

  await test.step("вакансия другой компании — только с флажком «Это вакансия нашей компании»", async () => {
    await open();
    const p = await preview("90000003");
    await expect(p).toContainText("Другая компания");
    const btn = dialog.getByRole("button", { name: "Создать черновик" });
    await expect(btn).toBeDisabled();
    await dialog.getByRole("checkbox", { name: /Это вакансия нашей компании/ }).check();
    await expect(btn).toBeEnabled();
    await dialog.getByRole("button", { name: "Закрыть" }).first().click();
  });

  await test.step("390: окно импорта без горизонтальной прокрутки", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open();
    const p = await preview("90000002");
    expect(await noHScroll(page), "окно импорта, 390 px").toBe(true);
    await p.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(DIR, "import-preview-390.png") });  // окно прокручено к предпросмотру
    await axe(page, '[role="dialog"]', "окно импорта 390");
    await dialog.getByRole("button", { name: "Закрыть" }).first().click();
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  await test.step("приглашение: «Рынок по hh.ru» рядом с вилкой — медиана, p25–p75 на руки, n, дата", async () => {
    const token = await juryToken(api, "employer");
    const needs = await apiGet<any[]>(api, "/employer/needs", token);
    const need = needs.find((n) => /Python|платеж/i.test(n.title)) ?? needs[0];
    const detail = await apiGet<any>(api, `/employer/needs/${need.id}`, token);
    const ver = detail.selections?.[0]?.version ?? detail.versions?.[0]?.version ?? 1;
    const sel = await apiGet<any>(api, `/employer/needs/${need.id}/selections/${ver}`, token);
    const find = (o: any): string | null => {
      if (!o || typeof o !== "object") return null;
      if (typeof o.ref === "string" && /^[A-Z]/.test(o.ref)) return o.ref;
      for (const v of Object.values(o)) { const r = find(v); if (r) return r; }
      return null;
    };
    const ref = find(sel);
    test.skip(!ref, "в подборке нет кандидатов");
    await page.goto(`/employer/candidates/${ref}?need=${need.id}`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Пригласить" }).click();
    const inv = page.getByRole("dialog", { name: "Приглашение-оффер" });
    const m = inv.getByTestId("hh-market");
    await expect(m).toBeVisible({ timeout: 30_000 });
    await expect(m).toContainText("Рынок по hh.ru");
    await expect(m).toContainText(/на руки, медиана|мало данных/);
    await expect(m).toContainText(/\d+ вакансий/);
    if (meta.hh?.stub) await expect(m).toContainText("данные не настоящие");
    await m.getByText("Как считали").click();
    await expect(m.getByRole("link", { name: /Тот же поиск на hh\.ru/ })).toHaveAttribute("href", /hh\.ru\/search\/vacancy/);
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "invite-market-1440");
    await axe(page, '[role="dialog"]', "приглашение 1440");
    await page.setViewportSize({ width: 390, height: 844 });
    await m.scrollIntoViewIfNeeded();
    await expect(m).toBeVisible();
    expect(await noHScroll(page), "приглашение, 390 px").toBe(true);
    await page.screenshot({ path: join(DIR, "invite-market-390.png") });  // окно прокручено к строке «Рынок по hh.ru»
  });
  await api.dispose();
});

test("/validation: блок «Разбор потребности на вакансиях hh.ru» — числа, дата и SHA, 1440 и 390", async ({ page }) => {
  const api = await apiContext();
  const meta = await (await api.get("/api/meta")).json();
  await api.dispose();
  test.skip(!meta.hh?.enabled, "интеграция hh.ru выключена (HH_ENABLED)");
  await page.goto("/validation#hh-parse", { waitUntil: "domcontentloaded" });
  const sec = page.locator("section#hh-parse");
  await expect(sec.getByRole("heading", { name: "Разбор потребности на вакансиях hh.ru" })).toBeVisible({ timeout: 60_000 });
  await expect(sec.getByTestId("hh-parse-signature")).toContainText(/код [0-9a-f]{7}/);
  await expect(sec.getByRole("cell", { name: /«Удалёнка не предусмотрена»/ })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Разбор на hh.ru" })).toBeVisible();
  await sec.scrollIntoViewIfNeeded();
  expect(await noHScroll(page)).toBe(true);
  await sec.screenshot({ path: join(DIR, "validation-1440.png") });
  await axe(page, "section#hh-parse", "блок /validation 1440");
  await page.setViewportSize({ width: 390, height: 844 });
  await sec.scrollIntoViewIfNeeded();
  expect(await noHScroll(page), "/validation, 390 px").toBe(true);
  await sec.screenshot({ path: join(DIR, "validation-390.png") });
});

test("/validation: «Подбор на реальных вакансиях hh.ru» — подпись «кандидаты модельные», спрос, 1440 и 390 (Я12б)", async ({ page }) => {
  const api = await apiContext();
  const meta = await (await api.get("/api/meta")).json();
  await api.dispose();
  test.skip(!meta.hh?.enabled, "интеграция hh.ru выключена (HH_ENABLED)");
  await page.goto("/validation#hh-match", { waitUntil: "domcontentloaded" });
  const sec = page.locator("section#hh-match");
  await expect(sec.getByRole("heading", { name: "Подбор на реальных вакансиях hh.ru" })).toBeVisible({ timeout: 60_000 });
  await expect(sec.getByTestId("hh-match-signature")).toContainText("кандидаты — модельные (модель, не люди)");
  await expect(sec.getByRole("cell", { name: "Нашлись кандидаты с подтверждённым тестом грейдом" })).toBeVisible();
  await expect(sec.getByRole("cell", { name: /DevOps \/ SRE/ }).first()).toBeVisible();
  await expect(sec.getByRole("heading", { name: "Спрос по направлениям на hh.ru" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Разделы" }).getByRole("link", { name: "Подбор на hh.ru" })).toBeVisible();
  await sec.scrollIntoViewIfNeeded();
  expect(await noHScroll(page)).toBe(true);
  await sec.screenshot({ path: join(DIR, "validation-match-1440.png") });
  await axe(page, "section#hh-match", "блок подбора /validation 1440");
  await page.setViewportSize({ width: 390, height: 844 });
  await sec.scrollIntoViewIfNeeded();
  expect(await noHScroll(page), "/validation#hh-match, 390 px").toBe(true);
  await sec.screenshot({ path: join(DIR, "validation-match-390.png") });
});

test("Кандидат: «Что сейчас просит рынок» в карте навыков — навыки hh.ru, статус и ссылка, 1440 и 390 (Я12б)", async ({ page }) => {
  const api = await apiContext();
  const meta = await (await api.get("/api/meta")).json();
  await api.dispose();
  test.skip(!meta.hh?.enabled, "интеграция hh.ru выключена (HH_ENABLED)");
  await juryEnter(page, "candidate");
  await page.goto("/candidate/feedback", { waitUntil: "domcontentloaded" });
  const sec = page.getByTestId("hh-market-skills");
  await expect(sec.getByRole("heading", { name: /^Что сейчас просит рынок/ })).toBeVisible({ timeout: 60_000 });
  await expect(sec).toContainText(/По \d+ вакансиям hh\.ru на \d\d\.\d\d\.\d{4}/);
  expect(await sec.getByRole("listitem").count()).toBeGreaterThan(2);
  const links = sec.getByRole("link", { name: /^(Подтвердить тестом|Короткое задание)$/ });
  if (await links.count()) await expect(links.first()).toHaveAttribute("href", /\/candidate\/(assessment|assignments)$/);
  await sec.scrollIntoViewIfNeeded();
  expect(await noHScroll(page)).toBe(true);
  await sec.screenshot({ path: join(DIR, "feedback-market-1440.png") });
  await axe(page, "[data-testid=hh-market-skills]", "«Что просит рынок» 1440");
  await page.setViewportSize({ width: 390, height: 844 });
  await sec.scrollIntoViewIfNeeded();
  expect(await noHScroll(page), "/candidate/feedback, 390 px").toBe(true);
  await sec.screenshot({ path: join(DIR, "feedback-market-390.png") });
});
