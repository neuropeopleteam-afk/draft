/** Прохождение адаптивного теста «вслепую» (первый вариант, третья строка кода, короткий текст) — общее для
 * сценариев 01 (без камеры) и 09 (с камерой). Ключи на клиент не попадают, поэтому грейд обычно не подтверждается;
 * проверяется механика выдачи заданий и подсчёта результата сервером. */
import { expect, type Page } from "@playwright/test";

export const RESULT = /^Грейд (не )?подтверждён$/;
const TEXT_ANSWER =
  "Сначала воспроизвожу дефект на минимальном входе, затем исправляю граничное условие и добавляю тест " +
  "на пустой ввод и на повтор запроса. Проверяю, что исправление не меняет поведение на остальных входах.";

/** Подпись текущего задания: «Задание N · отвечено M» + «Шаг k из n» — меняется после каждого ответа. */
export async function itemSignature(page: Page): Promise<string> {
  const main = page.getByRole("main");
  const progress = await main.getByText(/Задание \d+/).first().textContent().catch(() => "");
  const step = await main.getByText(/^Шаг \d+ из \d+$/).first().textContent({ timeout: 500 }).catch(() => "");
  return `${progress}|${step}`;
}

export async function answerCurrentItem(page: Page): Promise<string> {
  const main = page.getByRole("main");
  const radios = main.getByRole("radio");
  const lines = main.getByRole("listbox", { name: /Строки кода/ }).getByRole("option");
  const text = main.locator("textarea#ans");
  if (await radios.count()) { await radios.first().check(); return "option"; }
  if (await lines.count()) { await lines.nth(Math.min(2, (await lines.count()) - 1)).click(); return "line"; }
  if (await text.count()) {
    const isOutput = (await main.getByText("Вывод программы").count()) > 0;
    await text.fill(isOutput ? "0" : TEXT_ANSWER);
    return isOutput ? "output" : "text";
  }
  throw new Error("На экране задания нет ни вариантов, ни строк кода, ни поля ответа");
}

/** Отвечать до остановки движком; `between` вызывается после каждого принятого ответа (проверки по ходу теста). */
export async function runTestBlind(page: Page, between?: (answered: number) => Promise<void>): Promise<number> {
  const result = page.getByRole("heading", { name: RESULT });
  const submit = page.getByRole("button", { name: /^Ответить/ });
  let answered = 0;
  for (; answered < 60; answered++) {
    await expect(result.or(submit)).toBeVisible({ timeout: 90_000 });
    if (await result.isVisible()) break;
    const before = await itemSignature(page);
    await answerCurrentItem(page);
    await expect(submit).toBeEnabled();
    const resp = page.waitForResponse((r) => /\/api\/assessment\/sessions\/[^/]+\/answers$/.test(r.url())
      && r.request().method() === "POST", { timeout: 90_000 });
    await submit.click();
    expect((await resp).status(), "ответ принят сервером").toBe(200);
    await expect.poll(async () => (await result.isVisible()) || (await itemSignature(page)) !== before, { timeout: 90_000 }).toBe(true);
    if (between) await between(answered + 1);
  }
  await expect(result).toBeVisible({ timeout: 90_000 });
  return answered;
}
