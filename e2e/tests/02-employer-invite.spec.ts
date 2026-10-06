/**
 * Сценарий жюри, часть 2 (ТЗ п. 3.3, шаги «потребность → подборка → приглашение → ответ → контакты»):
 * демо-вход работодателем → потребность текстом → разбор требований → подборка с объяснениями «почему»
 * → обезличенная карточка → приглашение-оффер с вилкой → кандидат принимает → работодатель видит контакты.
 *
 * Приглашаем демо-кандидата «Мария Королёва» (Backend · Middle, паспорт ФСП). Её обезличенный номер берём из
 * API под её же демо-учёткой — так тест не зависит от случайного номера, который выдаётся при сбросе демо.
 */
import type { Browser, Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { installNetRetry } from "../lib/net";
import { apiContext, apiGet, juryToken } from "../lib/stand";
import { juryEnter, openSection } from "../lib/ui";

const RUN = new Date().toISOString().slice(11, 19).replace(/:/g, "");
const NEED =
  "Backend-разработчик middle в команду выплат: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. " +
  "Будет плюсом Docker и Kafka. Удалённо. Зарплата от 230 до 290 тыс.";
const POSITION = `Backend-разработчик выплат (e2e ${RUN})`;
const CANDIDATE_NAME = "Мария Королёва";

test.describe.configure({ mode: "serial" });

let ref = "";
let needUrl = "";

async function asPersona(browser: Browser, persona: "employer" | "candidate"): Promise<Page> {
  const ctx = await browser.newContext();
  await installNetRetry(ctx);
  const page = await ctx.newPage();
  await juryEnter(page, persona);
  return page;
}

test.beforeAll(async () => {
  const api = await apiContext();
  try {
    const me = await apiGet(api, "/me", await juryToken(api, "candidate"));
    ref = me.candidate.public_ref;
    expect(ref).toMatch(/^C-[A-Z0-9]+$/);
  } finally {
    await api.dispose();
  }
});

test("работодатель: потребность → подборка с объяснениями → приглашение", async ({ browser }) => {
  const page = await asPersona(browser, "employer");

  await test.step("потребность текстом и разбор требований", async () => {
    await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
    await expect(page.getByRole("heading", { name: "Потребности и подборки" })).toBeVisible();
    await page.locator("textarea#need").fill(NEED);
    await page.getByRole("button", { name: "Разобрать требования" }).click();
    await expect(page.getByRole("heading", { name: "Требования" })).toBeVisible({ timeout: 60_000 });
    await expect(page.locator("select#rd")).toHaveValue("backend");
    await expect(page.locator("select#rg")).toHaveValue("middle");
    for (const tag of ["Python", "FastAPI", "PostgreSQL"]) {
      await expect(page.getByText(tag, { exact: true }).filter({ visible: true }).first()).toBeVisible();
    }
    await expect(page.locator("input#rsf")).toHaveValue("230000");
    await expect(page.locator("input#rst")).toHaveValue("290000");
  });

  await test.step("подборка: категории, кандидаты, объяснение «почему»", async () => {
    await page.getByRole("button", { name: "Сохранить и показать подборку" }).click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
    needUrl = new URL(page.url()).pathname;
    await expect(page.getByRole("heading", { name: "Подходящие категории" })).toBeVisible();
    const total = page.getByText(/^v1 · кандидатов:/);
    await expect(total).toBeVisible();
    expect(Number((await total.locator("b").textContent()) ?? 0)).toBeGreaterThan(0);

    // блок «Почему в подборке» раскрыт сразу: по каждому требованию — факт и уровень доказанности
    const first = page.locator("details").filter({ has: page.getByText("Почему в подборке") }).first();
    await expect(first).toHaveAttribute("open", "");
    const reasons = first.locator("li");
    await expect(reasons.first()).toBeVisible();
    expect(await reasons.count(), "у кандидата есть объяснения по требованиям").toBeGreaterThan(1);
    await expect(first).toContainText(/Python/);
    await expect(first).toContainText(/T1|подтвержден/i);
    // ФИО в подборке не показываются — только обезличенный номер
    await expect(page.getByText(CANDIDATE_NAME)).toHaveCount(0);
    await expect(page.getByText(`Кандидат ${ref}`)).toBeVisible();
  });

  await test.step("обезличенная карточка из подборки", async () => {
    const card = page.locator("article").filter({ has: page.getByText(`Кандидат ${ref}`, { exact: true }) });
    await card.getByRole("link", { name: "Открыть" }).click();
    await expect(page).toHaveURL(new RegExp(`/employer/candidates/${ref}\\?need=`));
    await expect(page.getByRole("heading", { name: `Кандидат ${ref}` })).toBeVisible();
    await expect(page.getByText("Обезличенная карточка. Контакты откроются после принятия приглашения.")).toBeVisible();
    await expect(page.getByText(CANDIDATE_NAME)).toHaveCount(0);
    await expect(page.getByText(/Паспорт ФСП/).first()).toBeVisible();
  });

  await test.step("приглашение-оффер с обязательной вилкой", async () => {
    await page.getByRole("button", { name: "Пригласить" }).click();
    const dialog = page.getByRole("dialog", { name: "Приглашение-оффер" });
    await expect(dialog).toBeVisible();
    await dialog.locator("#it").fill(POSITION);
    await dialog.locator("#idesc").fill("Команда выплат: FastAPI, PostgreSQL, Redis. Удалённо, гибкий график. Проверка e2e.");
    await dialog.locator("#ic").fill("hr@jury.example.com");
    // вилка обязательна: пустое «до» не отправляется
    await dialog.locator("#sf").fill("240000");
    await dialog.locator("#st").fill("");
    await dialog.getByRole("button", { name: "Отправить приглашение" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Укажите вилку зарплаты");
    await dialog.locator("#st").fill("280000");
    await dialog.getByRole("button", { name: "Отправить приглашение" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("status").filter({ hasText: "Приглашение отправлено" })).toBeVisible();
    await expect(page.getByText(`Приглашение «${POSITION}»`)).toBeVisible();
    // не чаще раза в 30 дней
    await expect(page.getByRole("button", { name: "Пригласить" })).toBeDisabled();
  });
  await page.context().close();
});

test("кандидат принимает → работодатель видит контакты", async ({ browser }) => {
  test.skip(!needUrl, "приглашение не отправлено — смотрите предыдущий тест");

  await test.step("кандидат: приглашение с вилкой и доказательствами → принять", async () => {
    const page = await asPersona(browser, "candidate");
    await openSection(page, "Приглашения", /\/candidate\/invitations$/);
    await page.getByRole("button", { name: new RegExp(POSITION.replace(/[()]/g, "\\$&")) }).click();
    const dialog = page.getByRole("dialog", { name: POSITION });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Демо жюри: Северный платёж");
    await expect(dialog).toContainText(/240\s?000.*280\s?000/);
    await expect(dialog.getByText("На чём основано приглашение")).toBeVisible();
    await dialog.getByRole("button", { name: "Принять и открыть контакты" }).click();
    await expect(dialog.getByRole("status").filter({ hasText: "Вы приняли приглашение" })).toBeVisible();
    await page.context().close();
  });

  await test.step("работодатель: статус и контакты открыты", async () => {
    const page = await asPersona(browser, "employer");
    await openSection(page, "Приглашения", /\/employer\/invitations$/);
    const inv = page.locator("article").filter({ hasText: POSITION });
    await expect(inv.getByText("Контакты кандидата")).toBeVisible();
    await expect(inv).toContainText(CANDIDATE_NAME);
    await expect(inv).toContainText("candidate@jury.example.com");

    await inv.getByRole("link", { name: ref }).click();
    await expect(page.getByRole("heading", { name: `Кандидат ${ref}` })).toBeVisible();
    await expect(page.getByText("Кандидат принял ваше приглашение — контакты открыты.")).toBeVisible();
    await expect(page.getByText("Контакты", { exact: true })).toBeVisible();
    await expect(page.getByText(CANDIDATE_NAME).first()).toBeVisible();
    await page.context().close();
  });
});
