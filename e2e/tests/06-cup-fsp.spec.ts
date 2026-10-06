/**
 * Кубок работодателя и Кабинет ФСП.
 * Работодатель песочницы оценивает вслепую два оставшихся решения кубка «Вебхуки без дублей» по рубрике →
 * итоги подводятся сами → топ-3 получают приглашения (обезличенный номер вместо псевдонима). Кандидат видит
 * своё место в завершённом кубке. Федерация (ФСП) видит только агрегаты и выгрузки.
 */
import { expect, newPersonaContext, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const CUP = "Вебхуки без дублей";
const RUBRIC = [
  "Решение верное и работает в заданных условиях",
  "Обоснованы выбор и компромиссы, учтены крайние случаи",
  "Изложение ясное и проверяемое: шаги, код, тесты",
];

test("кубок: работодатель оценивает решения по рубрике → итоги → приглашения топ-3", async ({ page }) => {
  await juryEnter(page, "employer");
  await openSection(page, "Кубки", /\/employer\/cups$/);
  const main = page.getByRole("main");
  await main.getByRole("link", { name: new RegExp(CUP) }).click();
  await expect(main.getByRole("heading", { level: 1, name: CUP })).toBeVisible();
  const results = main.getByRole("heading", { level: 2, name: "Таблица результатов" }).locator("xpath=following::table[1]");

  await test.step("срок вышел, два решения ждут оценки; таблица без имён", async () => {
    await expect(main.getByText("Подведение итогов", { exact: true })).toBeVisible();
    await expect(main.getByText("ждут оценки: 2", { exact: true })).toBeVisible();
    await expect(main.getByRole("button", { name: "Подвести итоги" })).toBeDisabled();
    await expect(results.getByRole("row").filter({ hasText: "На оценке" })).toHaveCount(2);
    // до итогов — только псевдонимы «Участник NN», без обезличенных номеров и ссылок на карточки
    await expect(results.getByRole("cell", { name: /^Участник \d+/ })).toHaveCount(5);
    await expect(results.getByRole("link", { name: /^C-[A-Z0-9]+$/ })).toHaveCount(0);
    await expect(main.getByText(/Контакты и ПДн вырезаны из текста, ссылки скрыты/)).toBeVisible();
  });

  await test.step("оценка вслепую по рубрике", async () => {
    for (let i = 0; i < 2; i++) {
      const rate = main.getByRole("button", { name: "Оценить", exact: true }).first();
      await expect(rate).toBeDisabled();
      // у первого решения в очереди — верно и обосновано; у второго — частично
      for (const g of RUBRIC) {
        await main.getByRole("radiogroup", { name: g, exact: true }).first().getByRole("radio", { name: i ? "½" : "1", exact: true }).check();
      }
      await expect(rate).toBeEnabled();
      await rate.click();
      await expect(main.getByRole("button", { name: "Оценить", exact: true })).toHaveCount(1 - i, { timeout: 30_000 });
    }
  });

  await test.step("итоги подведены сами: топ-3 приглашены, номер вместо псевдонима", async () => {
    await expect(main.getByText("Завершён", { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(main.getByText("все оценены", { exact: true })).toBeVisible();
    await expect(main.getByText("3 приглашено", { exact: true })).toBeVisible();
    const rows = results.getByRole("rowgroup").nth(1).getByRole("row");
    await expect(rows).toHaveCount(5);
    for (let place = 1; place <= 5; place++) {
      const row = rows.nth(place - 1);
      await expect(row.getByRole("cell").first()).toHaveText(String(place));
      if (place <= 3) {
        await expect(row.getByRole("link", { name: /^C-[A-Z0-9]+$/ }), `место ${place}: обезличенный номер`).toBeVisible();
        await expect(row.getByRole("cell").last()).toHaveText("Отправлено");
      } else {
        await expect(row.getByRole("cell").last()).toHaveText("—");
      }
    }
    const scores = (await rows.locator("td:nth-child(3)").allTextContents()).map((t) => Number(t.replace(/\D/g, "")));
    expect(scores, "места по убыванию балла").toEqual([...scores].sort((a, b) => b - a));
  });

  await test.step("приглашения кубка в разделе «Приглашения»", async () => {
    const refs = await results.getByRole("link", { name: /^C-[A-Z0-9]+$/ }).allTextContents();
    await openSection(page, "Приглашения", /\/employer\/invitations$/);
    for (const ref of refs) {
      const inv = main.locator("article").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
      await expect(inv.first(), `приглашение ${ref}`).toContainText(/240\s000\s₽\s–\s290\s000\s₽/);
      await expect(inv.first()).toContainText("Отправлено");
    }
  });
});

test("кубок глазами кандидата: место в завершённом кубке", async ({ page }) => {
  await juryEnter(page, "candidate");
  await openSection(page, "Кубки работодателей", /\/candidate\/cups$/);
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1, name: "Кубки работодателей" })).toBeVisible();
  const done = main.getByRole("link").filter({ hasText: "Платёжный шлюз" });
  await expect(done).toContainText("Завершён");
  await expect(done).toContainText("Моё участие: Оценено · 2 место");
});

test("Кабинет ФСП: только агрегаты, период, разделы и выгрузки", async ({ browser }) => {
  const ctx = await newPersonaContext(browser);
  const page = await ctx.newPage();
  await juryEnter(page, "fsp");
  const main = page.getByRole("main");

  await test.step("обзор: показатели и главное за период", async () => {
    await expect(main.getByRole("heading", { level: 1, name: "Кабинет ФСП" })).toBeVisible();
    await expect(main.getByText("Только агрегаты · группы меньше 5 человек скрыты")).toBeVisible();
    const period = main.getByRole("radiogroup", { name: "Период" });
    await expect(period.getByRole("radio", { name: "Всё время" })).toBeChecked();
    const kpi = async () => Object.fromEntries(await Promise.all(["Кандидаты", "Работодатели", "Приглашения", "Кубки"].map(async (k) =>
      [k, Number((await main.getByText(k, { exact: true }).locator("xpath=following-sibling::p[1]").textContent())?.replace(/\D/g, ""))])));
    const all = await kpi();
    for (const [k, v] of Object.entries(all)) expect(v, k).toBeGreaterThan(0);
    expect(await main.getByRole("heading", { level: 2, name: "Главное за период" }).locator("xpath=following-sibling::ul[1]/li").count())
      .toBeGreaterThanOrEqual(3);
    await period.getByRole("radio", { name: "30 дней" }).check();
    await expect(period.getByRole("radio", { name: "30 дней" })).toBeChecked();
    await expect.poll(async () => (await kpi())["Приглашения"], { message: "за 30 дней приглашений не больше, чем за всё время" })
      .toBeLessThanOrEqual(all["Приглашения"]);
    // аналитика обезличена: имён демо-персон жюри в кабинете федерации нет
    await expect(main.getByText(/Мария Королёва|Илья Сергеев/)).toHaveCount(0);
  });

  const SECTIONS: [string, RegExp, string][] = [
    ["Спрос работодателей", /\/fsp\/demand$/, "Спрос работодателей"],
    ["Эффект соревнований ФСП", /\/fsp\/effect$/, "Эффект соревнований ФСП"],
    ["Зарплаты из офферов", /\/fsp\/salaries$/, "Зарплаты из офферов"],
    ["Воронки", /\/fsp\/funnel$/, "Воронки"],
    ["Кубки работодателей", /\/fsp\/cups$/, "Кубки работодателей"],
    ["Методика и выгрузки", /\/fsp\/method$/, "Методика и выгрузки"],
  ];
  for (const [nav, url, title] of SECTIONS) {
    await test.step(`раздел «${nav}»`, async () => {
      await openSection(page, nav, url);
      await expect(main.getByRole("heading", { level: 1, name: title })).toBeVisible();
    });
  }
  await test.step("выгрузка CSV", async () => {
    const download = page.waitForEvent("download");
    await main.getByRole("button", { name: "CSV: категории" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/\.csv$/);
    const body = await (await import("node:fs/promises")).readFile(await file.path(), "utf8");
    expect(body.split("\n").length, "строк в CSV").toBeGreaterThan(2);
  });
  await ctx.close();
});
