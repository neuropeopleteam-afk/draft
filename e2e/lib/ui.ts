/** Действия в интерфейсе, общие для сценариев: вход жюри в один клик с главной, проводник. */
import { expect, type Page } from "@playwright/test";
import type { Persona } from "./stand";

const TITLES: Record<Persona, string> = {
  candidate: "Кандидат с паспортом ФСП",
  candidate_nofsp: "Кандидат без ФСП",
  employer: "Работодатель",
  expert: "Эксперт",
};
const LANDING: Record<Persona, RegExp> = {
  candidate: /\/candidate$/, candidate_nofsp: /\/candidate$/, employer: /\/employer$/, expert: /\/expert$/,
};

/** Блок «Для экспертов жюри» на главной → «Войти как …». Проводник жюри должен открыться; скрываем его,
 * чтобы панель в правом нижнем углу не перекрывала кнопки. */
export async function juryEnter(page: Page, persona: Persona): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const block = page.locator("section#jury");
  await expect(block.getByRole("heading", { name: "Вход в один клик и проводник по сценарию" })).toBeVisible();
  await block.getByRole("button", { name: new RegExp(`^Войти как\\s*${TITLES[persona]}`) }).click();
  await expect(page).toHaveURL(LANDING[persona], { timeout: 60_000 });
  const guide = page.getByRole("complementary", { name: "Проводник для экспертов жюри" });
  await expect(guide).toBeVisible();
  await guide.getByRole("button", { name: "Скрыть проводник" }).click();
  await expect(guide).toBeHidden();
}

/** Переход по разделу кабинета через меню (как пользователь), без прямого ввода адреса. */
export async function openSection(page: Page, name: string, url: RegExp): Promise<void> {
  await page.getByRole("navigation").getByRole("link", { name, exact: true }).first().click();
  await expect(page).toHaveURL(url);
}
