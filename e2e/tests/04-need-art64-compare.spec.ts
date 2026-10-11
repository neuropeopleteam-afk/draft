/**
 * Потребность с нарушением ст. 64 ТК РФ → цитаты и предупреждение → переписать через навыки → подборка →
 * сравнение 2–3 кандидатов рядом по требованиям (кто выше и почему, цитата требования в каждой строке).
 * Работодатель — демо-компания песочницы прогона.
 */
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

// фрагменты примера «с нарушением ст. 64» (frontend/src/pages/employer/Needs.tsx) и ожидаемые категории фильтра
const ART64: [string, string][] = [
  ["только мужчины", "Пол"],
  ["до 35 лет", "Возраст"],
  ["славянской внешности", "Внешность, раса, национальность, язык"],
  ["без детей", "Семейное положение и дети"],
  ["молодой коллектив", "Возраст"],
];

test("потребность: ст. 64 → цитаты и предупреждение → через навыки → подборка → сравнение 3 кандидатов", async ({ page }) => {
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  const main = page.getByRole("main");
  const text = main.getByRole("textbox", { name: "Кого вы ищете" });

  await test.step("пример с нарушением: фрагменты подсвечены и вынесены в предупреждение", async () => {
    await main.getByRole("button", { name: "Пример с нарушением ст. 64 ТК РФ" }).click();
    await expect(text).toHaveValue(/только мужчины до 35 лет/);
    await main.getByRole("button", { name: "Разобрать требования" }).click();
    const warn = main.getByRole("status", { name: "Фильтр ст. 64 ТК РФ" });
    await expect(warn).toBeVisible({ timeout: 60_000 });
    await expect(warn.getByText(`Найдено фрагментов: ${ART64.length}.`, { exact: false })).toBeVisible();
    await expect(warn).toContainText("Они не попадут в требования и в ранжирование");
    for (const [quote, kind] of ART64) {
      const item = warn.getByRole("listitem").filter({ hasText: `«${quote}» · ${kind}` });
      await expect(item, `«${quote}»`).toBeVisible();
      await expect(item).toContainText("не связан");
      await expect(item).toContainText("Как лучше:");
      // цитата в исходном тексте подсвечена
      await expect(main.locator("mark").filter({ hasText: quote }).first()).toBeVisible();
    }
    // в требования ушли только навыки и условия, без пола и возраста
    await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible();
    await expect(main.getByRole("combobox", { name: "Направление", exact: true })).toHaveValue("backend");
    await main.getByRole("button", { name: "Настроить веса" }).click();  // Ф6 (В5): веса — по запросу
    for (const tag of ["Python", "Django", "PostgreSQL", "Docker"]) {
      await expect(main.getByRole("combobox", { name: `Вес: ${tag}`, exact: true }), tag).toBeVisible();
    }
  });

  await test.step("«Переписать через навыки» убирает фрагменты; повторный разбор без предупреждения", async () => {
    await main.getByRole("button", { name: "Переписать через навыки" }).click();
    for (const [quote] of ART64) await expect(text, `в тексте нет «${quote}»`).not.toHaveValue(new RegExp(quote));
    await expect(text).toHaveValue(/Python, Django и PostgreSQL/);
    const parse = main.getByRole("button", { name: "Разобрать требования" });
    if (await parse.isVisible()) await parse.click();
    await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible({ timeout: 60_000 });
    await expect(main.getByRole("status", { name: "Фильтр ст. 64 ТК РФ" })).toHaveCount(0);
  });

  await test.step("подборка по исправленной потребности", async () => {
    await main.getByRole("button", { name: /^(Подтвердить остальные и показать|Сохранить и показать) подборку$/ }).click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
    const total = main.getByText(/^версия 1 · кандидатов:/);
    await expect(total).toBeVisible();
    expect(Number((await total.locator("b").textContent()) ?? 0), "кандидатов в подборке").toBeGreaterThanOrEqual(3);
    // место в кубке — один раз («Кубок «…» — 2 место из 5»), θ — с запятой, как в сравнении
    await expect(main.getByText(/(\d+ место из \d+) — \1/), "место в кубке повторено").toHaveCount(0);
    await expect(main.getByText(/θ = [+−-]?\d+\.\d+/), "θ с десятичной точкой").toHaveCount(0);
  });

  await test.step("сравнение трёх кандидатов рядом", async () => {
    const compare = main.getByRole("button", { name: /^Сравнить выбранных \(\d\)$/ });
    await expect(compare).toBeDisabled();
    const picks = main.getByRole("checkbox", { name: "Сравнить", exact: true });  // Я10: галочка «Сравнить» на компактной карточке
    for (let i = 0; i < 3; i++) await picks.nth(i).check();
    await expect(compare).toHaveText("Сравнить выбранных (3)");
    await compare.click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+\/compare\?refs=C-[A-Z0-9]+(,C-[A-Z0-9]+){2}&v=1$/);
    await expect(main.getByRole("heading", { level: 1, name: "Сравнение кандидатов" })).toBeVisible();

    const table = main.getByRole("table", { name: "Сравнение кандидатов" });
    const heads = table.getByRole("columnheader", { name: /^C-[A-Z0-9]+ место \d+ из \d+/ });
    await expect(heads).toHaveCount(3);
    const places = (await heads.allTextContents()).map((t) => Number(/место\s*(\d+)\s*из/.exec(t)?.[1]));
    expect(places, "кандидаты по местам подборки").toEqual([...places].sort((a, b) => a - b));
    // каждая строка требования — с цитатой из текста потребности
    for (const tag of ["Python", "Django", "PostgreSQL"]) {
      await expect(table.getByRole("rowheader", { name: new RegExp(`^${tag} · вес [\\d,]+ «${tag}»`) }), tag).toBeVisible();
    }
    // пол, возраст и внешность в сравнение не попали («пол» — целым словом: подсказка строки «Оба направления»
    // содержит «дополнительное»)
    await expect(table.getByRole("rowheader", { name: /(^|[^а-яё])(пол(а|у|ом|е)?(?![а-яё])|возраст|мужчин|внешност|дет[еи]й)/i })).toHaveCount(0);

    const why = main.getByRole("region", { name: "Почему один кандидат выше другого" });
    // пара — «A выше B на N баллов из 100» или, если разница меньше 0,5 балла, «A и B почти равны: разница N балла из 100 — решит зонд»
    const pairs = why.getByRole("listitem").filter({
      hasText: /^C-[A-Z0-9]+ (выше C-[A-Z0-9]+ на [\d,]+ балл[а-я]* из 100|и C-[A-Z0-9]+ почти равны: разница [\d,]+ балл[а-я]* из 100 — решит зонд)/,
    });
    await expect(pairs).toHaveCount(2);
    await expect(main.getByRole("button", { name: "Зонд всем (3)" })).toBeVisible();
    await main.getByRole("link", { name: "К подборке" }).click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+\/v\/1$/);
  });
});
