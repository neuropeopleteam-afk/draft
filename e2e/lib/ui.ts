/** Действия в интерфейсе, общие для сценариев: вход жюри в один клик с главной, проводник. */
import { expect, type Page } from "@playwright/test";
import { sandboxId, type Persona } from "./stand";

// SIMPLIFY п.9: главные входы — компактный ряд («Кандидат», «Пройти тест с нуля», «Работодатель», «Федерация (ФСП)»),
// остальные роли — под «Ещё роли» (раскрываем перед кликом)
const TITLES: Record<Persona, string> = {
  candidate: "Кандидат",
  candidate_nofsp: "Кандидат без ФСП",
  candidate_junior: "Кандидат «Junior \\(предварительно\\)»",
  candidate_new: "Пройти тест с нуля",
  employer: "Работодатель",
  expert: "Эксперт",
  fsp: "Федерация \\(ФСП\\)",
};
const LANDING: Record<Persona, RegExp> = {
  candidate: /\/candidate$/, candidate_nofsp: /\/candidate$/, candidate_junior: /\/candidate(\/category)?$/, candidate_new: /\/candidate\/express$/,
  employer: /\/employer$/, expert: /\/expert$/,
  fsp: /\/fsp(\/[a-z]*)?$/,
};

/** Блок «Для экспертов жюри» на главной → «Войти как …» (вход в песочницу прогона). Проводник жюри должен
 * открыться; скрываем его, чтобы панель в правом нижнем углу не перекрывала кнопки. */
export async function juryEnter(page: Page, persona: Persona): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const block = page.locator("section#jury");
  await expect(block.getByRole("heading", { name: "Проверка для жюри" })).toBeVisible();
  const btn = block.getByRole("button", { name: new RegExp(`^Войти как:?\\s*${TITLES[persona]}$`) });
  if (!(await btn.isVisible())) await block.getByTestId("jury-more-roles").locator("summary").click();
  await btn.click();
  await expect(page).toHaveURL(LANDING[persona], { timeout: 60_000 });
  // вход — в песочницу прогона, а не в общее демо: фронтенд хранит её id там же, где мы его задали
  expect(await page.evaluate(() => localStorage.getItem("jury_scenario")), "песочница жюри в браузере").toBe(sandboxId());
  const guide = page.getByRole("complementary", { name: "Проводник для экспертов жюри" });
  // при первом входе в контексте проводник открыт; скрытый раньше в этом же браузере остаётся свёрнутым в кнопку
  const collapsed = page.getByRole("button", { name: "Показать проводник для жюри" });
  await expect(guide.or(collapsed)).toBeVisible();
  if (await guide.isVisible()) await guide.getByRole("button", { name: "Скрыть проводник" }).click();
  await expect(guide).toBeHidden();
  await expect(collapsed).toBeVisible();
}

/** Переход по разделу кабинета через меню (как пользователь), без прямого ввода адреса. */
export async function openSection(page: Page, name: string, url: RegExp): Promise<void> {
  // Ф6 (В4): второстепенные разделы кабинета — под кнопкой «Ещё N»; раскрываем, если ссылки нет
  const nav = page.getByRole("navigation");
  await expect(nav.getByRole("link", { name: "Обзор", exact: true }).first()).toBeVisible();
  const link = nav.getByRole("link", { name, exact: true }).first();
  if (!(await link.isVisible())) {
    const more = nav.getByRole("button", { name: /^Ещё \d+$/ });
    if (await more.count()) await more.first().click();
  }
  await link.click();
  await expect(page).toHaveURL(url);
}

/** /validation (SIMPLIFY): разделы ниже «5 чисел» свёрнуты — раскрыть все, как это сделает человек кнопкой
 *  «Раскрыть все разделы» в блоке «Как читать эту страницу». Проверки содержимого после этого — те же, что раньше. */
/** FINAL-UX E: «Подробные расчёты» — одна кнопка над всеми разделами ниже «5 чисел» и «Красной кнопки». */
export async function openFoldGroup(page: Page): Promise<void> {
  const g = page.getByTestId("fold-group-toggle");
  await expect(g).toBeVisible();
  if ((await g.getAttribute("aria-expanded")) !== "true") await g.click();
  await expect(g).toHaveAttribute("aria-expanded", "true");
}

export async function openAllFolds(page: Page): Promise<void> {
  await openFoldGroup(page);
  const btn = page.getByTestId("fold-all");
  await expect(btn).toBeVisible();
  if ((await btn.textContent())?.includes("Раскрыть")) await btn.click();
  await expect(btn).toHaveText("Свернуть все разделы");
}

/** Раскрыть один свёрнутый раздел /validation кнопкой «Показать раздел» под его заголовком. */
export async function openFold(page: Page, sectionSelector: string): Promise<void> {
  await openFoldGroup(page);
  const fold = page.getByTestId("fold").filter({ has: page.locator(sectionSelector) });
  const btn = fold.getByTestId("fold-toggle");
  if ((await btn.getAttribute("aria-expanded")) !== "true") await btn.click();
  await expect(btn).toHaveAttribute("aria-expanded", "true");
}
