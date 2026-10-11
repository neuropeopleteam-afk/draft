/**
 * Сценарий жюри, часть 2 (ТЗ п. 3.3, шаги «потребность → подборка → приглашение → ответ → контакты»):
 * демо-вход работодателем → потребность текстом → разбор требований → подборка с объяснениями «почему»
 * → обезличенная карточка → приглашение-оффер с вилкой → кандидат принимает → работодатель видит контакты.
 *
 * Приглашаем демо-кандидата «Мария Королёва» (Backend · Middle, паспорт ФСП). Её обезличенный номер берём из
 * API под её же демо-учёткой — так тест не зависит от случайного номера, который выдаётся при сбросе демо.
 */
import type { Browser, Page } from "@playwright/test";
import { expect, newPersonaContext, test } from "../lib/fixtures";
import { apiContext, apiGet, juryToken, sandboxId } from "../lib/stand";
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
  const ctx = await newPersonaContext(browser);
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

  await test.step("потребность текстом и разбор требований с цитатами", async () => {
    await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
    await expect(page.getByRole("heading", { level: 1, name: "Потребности и подборки" })).toBeVisible();
    await page.getByRole("textbox", { name: "Кого вы ищете" }).fill(NEED);
    await page.getByRole("button", { name: "Разобрать требования" }).click();
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible({ timeout: 60_000 });
    await expect(main.getByRole("combobox", { name: "Направление", exact: true })).toHaveValue("backend");
    await expect(main.getByRole("combobox", { name: "Грейд", exact: true })).toHaveValue("middle");
    await expect(main.getByRole("spinbutton", { name: "Вилка от, ₽" })).toHaveValue("230000");
    await expect(main.getByRole("spinbutton", { name: "Вилка до, ₽" })).toHaveValue("290000");
    await main.getByRole("button", { name: "Настроить веса" }).click();  // Ф6 (В5): веса — по запросу
    const row = (zone: string, tag: string) => main.getByRole("listitem")
      .filter({ has: page.getByRole("combobox", { name: `Вес: ${tag}`, exact: true }) }).filter({ hasText: `${zone}:` });
    for (const tag of ["Python", "FastAPI", "PostgreSQL", "Redis"]) await expect(row("Обязательно", tag), `обязательно ${tag}`).toBeVisible();
    for (const tag of ["Docker", "Kafka"]) await expect(row("Желательно", tag), `желательно ${tag}`).toBeVisible();
    // у каждого требования — цитата: фрагменты подсвечены в исходном тексте
    await expect(main.getByRole("heading", { level: 2, name: "Откуда взяты требования" })).toBeVisible();
    const marks = main.locator("mark");
    for (const q of ["middle", "Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "Kafka", "Удалённо"]) {
      await expect(marks.filter({ hasText: q }).first(), `цитата «${q}»`).toBeVisible();
    }
    // в тексте нет требований вне деловых качеств — фильтра ст. 64 нет
    await expect(main.getByRole("status", { name: "Фильтр ст. 64 ТК РФ" })).toHaveCount(0);
    await main.getByRole("button", { name: "Подтвердить все" }).click();
    await expect(main.getByText(/^Проверено требований: (\d+) из \1\./)).toBeVisible();
  });

  await test.step("подборка: категории, кандидаты, объяснение «почему»", async () => {
    await page.getByRole("button", { name: "Сохранить и показать подборку" }).click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
    needUrl = new URL(page.url()).pathname;
    await expect(page.getByRole("heading", { name: "Подходящие категории" })).toBeVisible();
    const total = page.getByText(/^версия 1 · кандидатов:/);
    await expect(total).toBeVisible();
    expect(Number((await total.locator("b").textContent()) ?? 0)).toBeGreaterThan(0);

    // Я10: первый экран — до 5 компактных карточек, «Пригласить» и «Сравнить» видны сразу
    const firstCard = page.locator('[data-testid="candidate-card"][data-compact="true"]').first();
    await expect(firstCard.getByRole("button", { name: "Пригласить", exact: true })).toBeVisible();
    await expect(firstCard.getByRole("checkbox", { name: "Сравнить", exact: true })).toBeVisible();
    expect(await page.locator('[data-testid="candidate-card"]').count(), "первый экран — не больше 5 карточек").toBeLessThanOrEqual(5);
    // доказательства: на широком блоке — справа, иначе — по «Подробнее»
    if (!(await page.getByTestId("side-details").isVisible())) await firstCard.getByRole("button", { name: /^Подробнее/ }).click();
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
    // кандидат может быть ниже первых пяти — остальные свёрнуты под «Показать ещё N» / «Показать всех (N)»
    const mine = page.getByText(`Кандидат ${ref}`, { exact: true });
    const more = page.getByRole("button", { name: /^Показать (всех \(\d+\)|ещё \d+)$/ });
    if (!(await mine.count()) && (await more.count())) await more.last().click();
    await expect(mine).toBeVisible();
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
    // FIX7 В1: неактивная кнопка объясняет себя — живой список недостающего со счётчиком знаков
    const missing = dialog.getByTestId("invite-missing");
    await expect(dialog.getByRole("button", { name: "Отправить приглашение" })).toBeDisabled();
    await expect(missing).toContainText("Чтобы отправить, заполните:");
    await expect(missing).toContainText("«Суть предложения» — ещё 20 знаков");
    await expect(dialog.getByText("Сокращённое рабочее время")).toHaveCount(0);  // взрослому кандидату — не нужно
    await dialog.locator("#it").fill(POSITION);
    await dialog.locator("#idesc").fill("Команда выплат");
    await expect(missing).toContainText("ещё 6 знаков");
    await expect(dialog.locator("#idesc")).toHaveAttribute("aria-invalid", "true");
    await dialog.locator("#idesc").fill("Команда выплат: FastAPI, PostgreSQL, Redis. Удалённо, гибкий график. Проверка e2e.");
    await dialog.locator("#ic").fill("hr@jury.example.com");
    await expect(missing).not.toContainText("Чтобы отправить");
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
    // демо-работодатель жюри — правдоподобные демо-сведения с пометкой «демо», индекс высокий (Ф4)
    await expect(dialog.getByText("Индекс доверия работодателя")).toBeVisible();
    await expect(dialog).toContainText("Высокий");
    await expect(dialog).toContainText("Сведения ФНС (демо)");
    await dialog.getByRole("button", { name: "Принять и открыть контакты" }).click();
    await expect(dialog.getByRole("status").filter({ hasText: "Вы приняли приглашение" })).toBeVisible();
    await page.context().close();
  });

  let emp!: Page;
  await test.step("работодатель: статус и контакты открыты", async () => {
    const page = (emp = await asPersona(browser, "employer"));
    await openSection(page, "Приглашения", /\/employer\/invitations$/);
    const inv = page.locator("article").filter({ hasText: POSITION });
    await expect(inv.getByText("Контакты кандидата")).toBeVisible();
    await expect(inv).toContainText(CANDIDATE_NAME);
    // почта демо-кандидата песочницы: candidate+<id песочницы>@jury.example.com
    await expect(inv).toContainText(`candidate+${sandboxId()}@jury.example.com`);

    await inv.getByRole("link", { name: ref }).click();
    await expect(page.getByRole("heading", { name: `Кандидат ${ref}` })).toBeVisible();
    await expect(page.getByText("Кандидат принял ваше приглашение — контакты открыты.")).toBeVisible();
    await expect(page.getByText("Контакты", { exact: true })).toBeVisible();
    await expect(page.getByText(CANDIDATE_NAME).first()).toBeVisible();
  });

  await test.step("работодатель: в карточке приглашения — состояние по каждой ATS, этап «Потока»", async () => {
    const page = emp;
    await openSection(page, "Приглашения", /\/employer\/invitations$/);
    const inv = page.locator("article").filter({ hasText: POSITION });
    // не «уже передано ранее» четыре раза, а строка на систему: «Передано: Поток · этап «Новые»»
    await expect(inv.getByText(/^Передано:/)).toHaveCount(4, { timeout: 60_000 });
    await expect(inv.getByText(/^Передано: Поток · этап «Новые»/)).toBeVisible();
    await expect(inv.getByText("уже передано ранее")).toHaveCount(0);
  });

  await test.step("работодатель: журнал передач в ATS после принятия", async () => {
    const page = emp;
    await openSection(page, "Интеграция с ATS", /\/employer\/ats$/);
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1, name: "Интеграция с ATS" })).toBeVisible();
    const journal = main.getByRole("table").filter({ has: page.getByRole("columnheader", { name: "Куда" }) });
    await expect(main.getByRole("heading", { level: 2, name: "Журнал передач" })).toBeVisible();
    // FIX7 В2: первая вкладка — «Поток», остальные — в «Другие ATS»; в «Реальный» — откуда токен; причина неактивной проверки
    const atsSeg = main.getByRole("radiogroup", { name: "ATS" });
    await expect(atsSeg.getByRole("radio").first()).toHaveText(/^«Поток»/);
    await expect(atsSeg.getByRole("radio").first()).toHaveAttribute("aria-checked", "true");
    await expect(atsSeg.getByRole("radio", { name: /^Другие ATS/ })).toBeVisible();
    await expect(main.getByTestId("ats-live-check")).toContainText("docs/integrations/LIVE_CHECKS.md");
    await main.getByRole("radiogroup", { name: "Режим" }).getByRole("radio", { name: "Реальный" }).click();
    await expect(main.getByTestId("ats-token-from")).toContainText("Настройки компании → «Генерация токенов»");
    await expect(main.getByRole("button", { name: "Проверить подключение" })).toBeDisabled();
    await expect(main.getByTestId("ats-check-why")).toContainText("сначала вставьте токен");
    await main.getByRole("radiogroup", { name: "Режим" }).getByRole("radio", { name: "Демо" }).click();
    await atsSeg.getByRole("radio", { name: /^Другие ATS/ }).click();
    await expect(main.getByRole("radiogroup", { name: "Другие ATS" }).getByRole("radio", { name: /^Talantix/ })).toHaveAttribute("aria-checked", "true");
    // принятое приглашение уходит автоматически во все подключённые демо-ATS
    for (const ats of ["Talantix", "Поток", "Хантфлоу", "Вебхук"]) {
      const row = journal.getByRole("row").filter({ hasText: POSITION }).filter({ has: page.getByRole("cell", { name: ats, exact: true }) });
      await expect(row, `передача в ${ats}`).toHaveCount(1, { timeout: 60_000 });
      await expect(row.getByRole("cell", { name: /^передано/ })).toBeVisible();
    }
    // что пришло в тестовую ATS: профиль с контактами — только кандидаты своей песочницы
    const inbox = main.getByRole("heading", { level: 2, name: "Тестовая ATS: что пришло" }).locator("xpath=following-sibling::ul[1]");
    await expect(inbox.getByRole("listitem").filter({ hasText: `${CANDIDATE_NAME.split(" ").reverse().join(" ")} · candidate+${sandboxId()}@jury.example.com` }).first()).toBeVisible();
    const emails = (await inbox.textContent())?.match(/[\w.+-]+@jury\.example\.com/g) ?? ([] as string[]);
    expect(emails.filter((e) => !e.includes(`+${sandboxId()}@`)), "в тестовой ATS нет кандидатов чужих песочниц").toEqual([]);
    await page.context().close();
  });
});
