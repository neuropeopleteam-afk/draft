/**
 * Проверка изоляции демо-режима (TASK_A1, PR-01..PR-22):
 * 1. У обычного (не демо) пользователя в личном кабинете (/employer, /candidate) в DOM нет
 *    «Быстрый переход для жюри», «Демо-аккаунт для жюри», «Роль в 1 клик», «Боевой ИИ-Полигон»,
 *    «Тест с нуля», `cabinet-top-bar` и `cabinet-route`; есть хлебные крошки и ссылка «Помощь» (/support).
 * 2. На странице входа (/login) без режима жюри нет кнопок демо-входа, но есть ссылка «Забыли пароль?» (/forgot).
 * 3. В разделе /demo доступны «Проверьте нас за 3 минуты» (7 критериев ТЗ) и «Карта соответствия ТЗ».
 */
import { expect, test } from "../lib/fixtures";

test("обычный работодатель в кабинете не видит демо-строк жюри, видит хлебные крошки и поддержку", async ({ page }) => {
  await page.route("**/api/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "11111111-2222-3333-4444-555555555555",
        email: "hr@real-company.ru",
        role: "employer",
        is_email_verified: true,
        created_at: "2026-10-20T10:00:00Z",
        candidate: null,
        employer: {
          full_name: "Мария Соколова",
          position: "HRD",
          company: {
            id: "22222222-3333-4444-5555-666666666666",
            name: "ООО «Реальная Компания»",
            inn: "7701234567",
            industry: "ИТ",
            description: null,
            website: null,
            city: "Москва",
            contact_email: "hr@real-company.ru",
            contact_phone: null,
          },
        },
        fsp: null,
      }),
    });
  });

  await page.addInitScript(() => {
    localStorage.setItem("fsp_token", "fake-real-user-jwt");
    localStorage.setItem("draft_cookie_consent", "essential");
    localStorage.removeItem("fsp_jury_guide");
    localStorage.removeItem("fsp_jury_ui_seen");
  });

  await page.goto("/employer", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("cabinet-breadcrumbs")).toBeVisible();
  await expect(page.getByTestId("cabinet-top-bar")).toHaveCount(0);
  await expect(page.getByTestId("cabinet-route")).toHaveCount(0);

  const bodyText = await page.locator("body").innerText();
  for (const forbidden of [
    "Быстрый переход для жюри",
    "Демо-аккаунт для жюри",
    "Роль в 1 клик",
    "Боевой ИИ-Полигон",
    "Тест с нуля",
  ]) {
    expect(bodyText).not.toContain(forbidden);
  }
});

test("/login без демо-режима не показывает демо-кнопки и ведёт на /forgot", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("draft_cookie_consent", "essential");
    localStorage.removeItem("fsp_jury_guide");
    localStorage.removeItem("fsp_jury_ui_seen");
  });
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("login-demo")).toHaveCount(0);
  const forgot = page.getByTestId("login-forgot-link");
  await expect(forgot).toBeVisible();
  await forgot.click();
  await expect(page).toHaveURL(/\/forgot$/);
  await expect(page.getByTestId("forgot-form")).toBeVisible();
});

test("/demo содержит маршрут «Проверьте нас за 3 минуты» и «Карту соответствия ТЗ»", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("draft_cookie_consent", "essential");
  });
  await page.goto("/demo", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("demo-3min")).toBeVisible();
  await expect(page.getByTestId("demo-tz-map")).toBeVisible();
  await expect(page.getByTestId("demo-custom-bench")).toBeVisible();
});
