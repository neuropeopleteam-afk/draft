/** Действия в интерфейсе, общие для сценариев: вход жюри в один клик с главной, проводник. */
import { expect, type Page } from "@playwright/test";
import { sandboxId, type Persona } from "./stand";

const TITLES: Record<Persona, string> = {
  candidate: "Кандидат с паспортом ФСП",
  candidate_nofsp: "Кандидат без ФСП",
  candidate_new: "Пройдите тест сами",
  employer: "Работодатель",
  expert: "Эксперт",
  fsp: "Федерация \\(ФСП\\)",
};
const LANDING: Record<Persona, RegExp> = {
  candidate: /\/candidate$/, candidate_nofsp: /\/candidate$/, candidate_new: /\/candidate\/express$/, employer: /\/employer$/, expert: /\/expert$/,
  fsp: /\/fsp(\/[a-z]*)?$/,
};

/** Блок «Для экспертов жюри» на главной → «Войти как …» (вход в песочницу прогона). Проводник жюри должен
 * открыться; скрываем его, чтобы панель в правом нижнем углу не перекрывала кнопки. */
export async function juryEnter(page: Page, persona: Persona): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const block = page.locator("section#jury");
  await expect(block.getByRole("heading", { name: "Вход в один клик и проводник по сценарию" })).toBeVisible();
  await block.getByRole("button", { name: new RegExp(`^Войти как:?\\s*${TITLES[persona]}`) }).click();
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
  await page.getByRole("navigation").getByRole("link", { name, exact: true }).first().click();
  await expect(page).toHaveURL(url);
}
