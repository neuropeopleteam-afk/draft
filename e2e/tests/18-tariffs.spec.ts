/**
 * Тарифы работодателя и «Польза для ФСП» (Я29, docs/TARIFFS.md). Только на стенде с TARIFFS_ENABLED=1 — иначе спек
 * пропускается. Цены — демонстрационные, оплаты нет (демо-счёт).
 *
 * 1. Публичная /tariffs: три тарифа, «кандидатам — бесплатно», ориентиры рынка со ссылками; 1440 и 390 px без
 *    горизонтальной прокрутки; axe.
 * 2. Работодатель песочницы («Северный платёж», «Найм» по умолчанию): «Тарифы» → остаток приглашений → «Старт» →
 *    снова «Найм» с демо-счётом (№, сумма, НДС 22 %); счётчик в форме приглашения; 390 px; axe.
 * 3. Метка «Партнёр ФСП»: «Логистика Онлайн» песочницы — партнёр по умолчанию; карточка компании у кандидата.
 * 4. Кабинет ФСП: «Польза для ФСП» (регионы, направления, партнёры, CSV) и «Партнёры ФСП» (заявки, снятие/выдача метки
 *    своей компании песочницы; демо-компании общего стенда — только просмотр); 390 px; axe.
 * Снимки — в E2E_SHOTS_DIR/tariffs. axe (WCAG 2.1 A/AA, critical/serious = 0) — если задан E2E_AXE.
 */
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { apiContext, juryToken } from "../lib/stand";
import { juryEnter, openSection } from "../lib/ui";

const DIR = join(process.env.E2E_SHOTS_DIR || "reports", "tariffs");
mkdirSync(DIR, { recursive: true });
const AXE = process.env.E2E_AXE || "";

async function shot(page: Page, name: string): Promise<void> {
  const file = join(DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}
const noHScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

async function axe(page: Page, scope: string, label: string): Promise<void> {
  if (!AXE || !existsSync(AXE)) { test.info().annotations.push({ type: "axe", description: "E2E_AXE не задан — пропущено" }); return; }
  if (!(await page.evaluate(() => "axe" in window))) await page.addScriptTag({ path: AXE });
  const res = await page.evaluate(async (sel) => {
    // @ts-expect-error axe — глобальный объект из axe.min.js
    const r = await window.axe.run(sel, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
    return r.violations.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
  }, scope);
  test.info().annotations.push({ type: "axe", description: `${label}: ${JSON.stringify(res)}` });
  expect(res, `axe ${label}`).toEqual([]);
}

async function at390(page: Page, name: string): Promise<void> {
  const size = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  expect(await noHScroll(page), `${name}: без горизонтальной прокрутки на 390`).toBe(true);
  await shot(page, `${name}-390`);
  if (size) await page.setViewportSize(size);
}

test.describe.configure({ mode: "serial" });

test("тарифы: публичная страница, кабинет работодателя, демо-счёт, метка партнёра, «Польза для ФСП»", async ({ page }) => {
  const api = await apiContext();
  const meta = await (await api.get("/api/meta")).json();
  test.skip(!meta.tariffs?.enabled, "тарифы выключены (TARIFFS_ENABLED)");

  await test.step("публичная /tariffs: три тарифа, ориентиры рынка", async () => {
    await page.goto("/tariffs", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Тарифы", level: 1 })).toBeVisible();
    for (const t of ["Старт", "Найм", "Партнёр ФСП"]) await expect(page.getByRole("article", { name: `Тариф «${t}»` })).toBeVisible();
    await expect(page.getByText("Кандидатам — всегда бесплатно", { exact: false }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: /Хабр Карьера/ }).first()).toHaveAttribute("href", /career\.habr\.com/);
    await expect(page.getByText(/демонстрационные, не оферта/)).toBeVisible();
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "public-1440");
    await axe(page, "main", "публичная /tariffs");
    await at390(page, "public");
  });

  await test.step("работодатель: «Тарифы» → «Старт» → «Найм» с демо-счётом; счётчик в кабинете", async () => {
    await juryEnter(page, "employer");
    await expect(page.getByTestId("invites-left")).toContainText("осталось");
    await openSection(page, "Тарифы", /\/employer\/tariffs$/);
    await expect(page.getByRole("article", { name: "Тариф «Найм»" })).toContainText("Ваш тариф");
    await expect(page.getByTestId("tariff-left")).toContainText(/осталось \d+ из 30/);
    await page.getByRole("button", { name: "Перейти на «Старт»" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Тариф «Старт» подключён" })).toBeVisible();
    await expect(page.getByTestId("tariff-left")).toContainText(/из 3$/);
    await page.getByRole("button", { name: /Подключить за 9\s900\s₽ \(демо-счёт\)/ }).click();
    const ok = page.getByRole("status").filter({ hasText: "демонстрационный счёт" });
    await expect(ok).toBeVisible();
    await expect(ok).toContainText("оплата не проводится");
    await expect(page.getByTestId("demo-invoice").first()).toContainText(/НДС 22 %: 1\s785\s₽/);
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "employer-1440");
    await axe(page, "main", "кабинет работодателя: Тарифы");
    await at390(page, "employer");
    await openSection(page, "Приглашения", /\/employer\/invitations$/);
    await expect(page.getByTestId("invites-left")).toContainText("Тариф «Найм»");
  });

  await test.step("метка «Партнёр ФСП»: карточка компании-партнёра у кандидата", async () => {
    const tf = await juryToken(api, "fsp");
    const ov = await (await api.get("/api/fsp-cabinet/partners", { headers: { Authorization: `Bearer ${tf}` } })).json();
    const own = ov.partners.find((p: any) => p.can_manage);
    expect(own, "компания-партнёр своей песочницы").toBeTruthy();
    await juryEnter(page, "candidate");
    await page.goto(`/candidate/companies/${own.company_id}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: own.name })).toBeVisible();
    await expect(page.getByTestId("fsp-partner-badge")).toBeVisible();
    await axe(page, "main", "карточка компании-партнёра");
  });

  await test.step("Кабинет ФСП: «Польза для ФСП» и «Партнёры ФСП»", async () => {
    await juryEnter(page, "fsp");
    await openSection(page, "Польза для ФСП", /\/fsp\/benefit$/);
    await expect(page.getByRole("heading", { name: "По регионам" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "По направлениям" })).toBeVisible();
    const partners = page.getByRole("table", { name: "Партнёры ФСП: приглашения и наймы" });
    await expect(partners).toContainText("Демо: КиберЩит");
    await expect(page.getByText(/группы меньше 5 человек скрыты/)).toBeVisible();
    const dl = page.waitForEvent("download");
    await page.getByRole("button", { name: "CSV: польза для ФСП" }).click();
    expect((await dl).suggestedFilename()).toBe("fsp_benefit.csv");
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "fsp-benefit-1440");
    await axe(page, "main", "Польза для ФСП");
    await at390(page, "fsp-benefit");

    await openSection(page, "Партнёры ФСП", /\/fsp\/partners$/);
    const rows = page.getByTestId("partner-row");
    await expect(rows.filter({ hasText: "Демо: ПромИИ" })).toContainText("Менять метку этой компании из демо-песочницы нельзя");
    const mine = rows.filter({ has: page.getByRole("button", { name: "Снять метку" }) }).first();
    await expect(mine).toBeVisible();
    const name = (await mine.locator("span.font-semibold").first().innerText()).trim();
    await mine.getByRole("button", { name: "Снять метку" }).click();
    await page.getByRole("textbox", { name: "Название или ИНН (от 3 символов)" }).fill(name.slice(-8));
    await page.getByRole("button", { name: "Найти" }).click();
    const found = rows.filter({ hasText: name }).filter({ has: page.getByRole("button", { name: "Выдать метку «Партнёр ФСП»" }) });
    await expect(found).toBeVisible();
    await found.getByRole("button", { name: "Выдать метку «Партнёр ФСП»" }).click();
    await expect(page.getByRole("heading", { name: /^Партнёры \(\d+\)$/ })).toBeVisible();
    await expect(rows.filter({ hasText: name }).first()).toContainText("Партнёр ФСП");
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "fsp-partners-1440");
    await axe(page, "main", "Партнёры ФСП");
    await at390(page, "fsp-partners");
  });
});
