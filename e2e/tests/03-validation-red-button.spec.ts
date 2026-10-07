/**
 * Сценарий жюри, часть 3: «Как мы проверяем себя» (/validation) и «Красная кнопка».
 * Страница открыта без входа. Каждая атака выполняется на живых демо-данных в памяти и ничего не записывает;
 * ожидаемое свойство должно выполняться: раздувание резюме, смена имени, смена пола/возраста/имени у всего пула,
 * фальшивый и убранный значок ФСП не меняют подбор сверх правил, утечка части банка ловится детектором.
 * Блоки страницы: бенчмарк подбора со скрытой истиной, сравнение с ориентирами в их условиях, экспертная разметка.
 */
import { expect, test } from "../lib/fixtures";

const ATTACKS = [
  "Раздуть резюме ключевыми словами",
  "Поменять имя при тех же навыках",
  "Сменить пол, возраст и имя",
  "Добавить неподтверждённый значок ФСП",
  "Убрать историю ФСП",
  "«Слить» часть банка заданий",
];

test("главная → «Красная кнопка» ведёт на /validation#red-button", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("section#jury").getByRole("link", { name: "Красная кнопка" }).click();
  await expect(page).toHaveURL(/\/validation#red-button$/);
  await expect(page.getByRole("heading", { name: "Красная кнопка: атакуйте сами" })).toBeInViewport();
});

test("/validation: метрики теста и подбора на месте", async ({ page }) => {
  await page.goto("/validation", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Как мы проверяем себя" })).toBeVisible();
  const SECTIONS: Record<string, string> = {
    bank: "Банк заданий и калибровка", test: "Тест: точность оценки и решения по грейду (симуляция)",
    retest: "Стабильность грейда при повторе", others: "В других условиях", exposure: "Частота показа заданий",
    leak: "Устойчивость к утечке части банка", matching: "Качество подбора", bench: "Бенчмарк подбора со скрытой истиной",
    experts: "Экспертная разметка: подбор, модель-оценщик, пороги грейдов", live: "Живые данные платформы",
    "red-button": "Красная кнопка: атакуйте сами",
  };
  for (const [id, title] of Object.entries(SECTIONS)) {
    await expect(page.locator(`section#${id}`).getByRole("heading", { level: 2, name: title, exact: true }), `раздел #${id}`).toBeVisible();
  }
  // цифры приходят из отчёта валидации (GET /api/validation/report), а не зашиты в вёрстку
  const report = await page.request.get("/api/validation/report");
  expect(report.ok()).toBeTruthy();
  const body = await report.json();
  expect(Object.keys(body)).toEqual(expect.arrayContaining(["live", "attacks"]));
  await expect(page.locator("section#matching")).toContainText(/nDCG|BM25/);
});

test("/validation: бенчмарк со скрытой истиной, другие условия, экспертная разметка", async ({ page }) => {
  await page.goto("/validation#bench", { waitUntil: "domcontentloaded" });
  await test.step("бенчмарк подбора: платформа против BM25 с доверительными интервалами", async () => {
    const bench = page.locator("section#bench");
    await expect(bench.getByText(/потребностей × [\d\s ]+ кандидатов = [\d\s ]+ пар синтетического мира/)).toBeVisible();
    const ndcg = bench.getByText("nDCG@10 платформы", { exact: true }).locator("xpath=following-sibling::p[1]");
    const value = Number((await ndcg.textContent())?.replace(",", "."));
    await expect(bench.getByText(/^95 % ДИ \d,\d+–\d,\d+ · BM25 \d,\d+$/)).toBeVisible();
    const bm25 = Number(/BM25 (\d,\d+)/.exec((await bench.getByText(/^95 % ДИ/).textContent()) ?? "")?.[1].replace(",", "."));
    expect(value, "nDCG@10 платформы выше BM25").toBeGreaterThan(bm25);
    await expect(bench.getByRole("heading", { level: 3, name: /^Метрики: среднее по потребностям и 95 % ДИ/ })).toBeVisible();
    await expect(bench.getByRole("table").first().getByRole("columnheader", { name: "nDCG@10" })).toBeVisible();
    // честность: синтетика проверяет механику, а не реальный рынок — это сказано прямо
    await expect(bench.getByRole("status").filter({ hasText: /^Честно:/ })).toBeVisible();
  });
  await test.step("ориентиры: наш тест в их условиях симуляции", async () => {
    const table = page.locator("section#others").getByRole("table");
    for (const who of [/^Прототип А, их симуляция/, /^Наш тест в их условиях/, /^Наш тест в наших условиях/]) {
      await expect(table.getByRole("row").filter({ has: page.getByRole("cell", { name: who }) }), String(who)).toHaveCount(1);
    }
    await expect(table.getByRole("columnheader", { name: "κ с истиной" })).toBeVisible();
  });
  await test.step("экспертная разметка: три задания и проверка расчёта", async () => {
    const experts = page.locator("section#experts");
    for (const part of ["A · пары «потребность — кандидат»", "B · ответы по рубрике", "C · семейства для Ангоффа"]) {
      await expect(experts.getByText(part, { exact: true })).toBeVisible();
    }
    await expect(experts.getByRole("group").filter({ hasText: /^Проверка расчёта на синтетической разметке · пройдена/ })).toBeVisible();
  });
  await test.step("экспертная разметка: честная подпись источника (люди или прогоны модели)", async () => {
    const experts = page.locator("section#experts");
    const ex = (await (await page.request.get("/api/validation/report")).json()).experts ?? {};
    const caption = experts.getByTestId("experts-model-caption");
    if (!ex.model_panel) {
      // панель людей (или смешанная) — модельной подписи и пометок модельной панели нет
      await expect(caption).toHaveCount(0);
      await expect(experts.getByTestId("experts-agreement-caveat")).toHaveCount(0);
      if (ex.source?.title) await expect(experts.getByText(`Источник разметки: ${ex.source.title}.`, { exact: true })).toBeVisible();
      if (ex.source?.kind === "people" && ex.labels > 0 && ex.agreement?.A) {
        await expect(experts.getByRole("heading", { level: 3, name: "Межэкспертное согласие", exact: true }).first()).toBeVisible();
      }
      return;
    }
    // вся панель — прогоны модели: подпись, пояснение к κ/α, нейтральный вывод, Ангофф справочно
    await expect(caption).toContainText(`Разметка выполнена моделью ${ex.source.models[0]}`);
    await expect(caption).toContainText("это проверка конвейера и методики, а не замена экспертной панели");
    await expect(experts.getByText(/тимлиды и сеньоры/)).toHaveCount(0);
    if (ex.labels > 0 && ex.agreement?.A) {
      await expect(experts.getByTestId("experts-agreement-caveat")).toContainText("согласие завышено: прогоны одной модели коррелированы");
      await expect(experts.getByRole("cell", { name: "надёжно", exact: true })).toHaveCount(0);
      await expect(experts.getByRole("cell", { name: "согласие прогонов модели", exact: true }).first()).toBeVisible();
    }
    if (ex.llm) await expect(experts.getByRole("heading", { level: 3, name: /против консенсуса модельной панели$/ })).toBeVisible();
    if (ex.angoff) {
      await expect(experts.getByRole("heading", { level: 3, name: /Ангофф против текущих — справочно, модельная панель$/ })).toBeVisible();
      await expect(experts.getByRole("cell", { name: "предложить новый порог", exact: true })).toHaveCount(0);
    }
  });
});

test("«Красная кнопка»: шесть атак, ожидаемые свойства выполнены", async ({ page }) => {
  test.setTimeout(3 * 60_000);
  await page.goto("/validation#red-button", { waitUntil: "domcontentloaded" });
  const section = page.locator("section#red-button");
  await expect(section.getByRole("heading", { name: "Красная кнопка: атакуйте сами" })).toBeVisible();
  await expect(section.locator("article"), "все атаки на месте").toHaveCount(ATTACKS.length);
  for (const title of ATTACKS) {
    await test.step(title, async () => {
      const card = section.locator("article").filter({ has: page.getByText(title, { exact: true }) });
      await card.getByRole("button", { name: /Запустить/ }).click();
      const verdict = card.getByRole("status");
      await expect(verdict).toBeVisible({ timeout: 90_000 });
      await expect(verdict).toContainText("Свойство выполнено");
      await expect(verdict).toContainText("ничего не записано");
      await expect(verdict).toContainText(/Факт:/);
    });
  }
});
