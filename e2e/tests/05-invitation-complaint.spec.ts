/**
 * Жалоба кандидата на приглашение: Илья (демо-кандидат без ФСП в песочнице) жалуется на приглашение
 * «Backend-разработчик (платежи)» → приглашение отклонено с причиной, жалоба одна, индекс доверия компании
 * учитывает её (видят другие кандидаты), работодатель видит причину без комментария кандидата.
 */
import { expect, newPersonaContext, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const POSITION = "Backend-разработчик (платежи)";
const COMMENT = "Проверка e2e: на звонке описали другую роль.";

test("кандидат жалуется на приглашение → отклонено, индекс доверия учитывает, работодатель видит причину", async ({ page, browser }) => {
  await juryEnter(page, "candidate_nofsp");
  await openSection(page, "Приглашения", /\/candidate\/invitations$/);
  await page.getByRole("button", { name: new RegExp(`^${POSITION.replace(/[()]/g, "\\$&")}`) }).click();
  const dialog = page.getByRole("dialog", { name: POSITION });
  const complaints = dialog.getByRole("listitem").filter({ hasText: /Жалобы кандидатов\./ });

  // число индекса — крупная цифра рядом с «из 100»
  const score = async () => Number(await dialog.locator("p", { hasText: "из 100" }).first().locator("span").first().textContent());
  let before = 0;
  await test.step("до жалобы: индекс доверия без жалоб", async () => {
    await expect(dialog.getByText("Индекс доверия работодателя")).toBeVisible();
    await expect(complaints).toContainText("жалоб на приглашения нет");
    before = await score();
  });

  await test.step("жалоба с причиной и комментарием", async () => {
    await dialog.getByRole("button", { name: /^Пожаловаться/ }).click();
    const reason = dialog.getByRole("radiogroup", { name: "Причина жалобы" });
    for (const r of ["Нереальная вилка", "Не та роль", "Спам", "Другое"]) await expect(reason.getByRole("radio", { name: r })).toBeVisible();
    await reason.getByRole("radio", { name: "Не та роль" }).check();
    await dialog.getByRole("textbox", { name: /^Комментарий/ }).fill(COMMENT);
    await expect(dialog.getByText(/Жалоба снижает индекс доверия работодателя; приглашение будет отклонено/)).toBeVisible();
    await dialog.getByRole("button", { name: "Отправить жалобу" }).click();
    await expect(dialog.getByRole("status").filter({ hasText: /^Жалоба отправлена: не та роль\./ })).toBeVisible();
    await expect(dialog.getByRole("listitem").filter({ hasText: /^Отклонено · .* · кандидат/ })).toContainText("«Жалоба: не та роль»");
    // жалоба одна: ни повторной жалобы, ни «принять» после неё
    await expect(dialog.getByRole("button", { name: /^Пожаловаться/ })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Принять и открыть контакты" })).toHaveCount(0);
    // индекс доверия обновляется в том же окне: строка жалоб и −5 баллов (не ниже 0)
    await expect(complaints).toContainText(/жалоб за полгода: 1 из \d+ приглашений \(не та роль — 1\)/);
    await expect.poll(score, { message: "жалоба снижает индекс на 5" }).toBe(Math.max(0, before - 5));
  });

  await test.step("индекс доверия компании учитывает жалобу", async () => {
    await dialog.getByRole("button", { name: "Закрыть" }).click();
    await page.getByRole("button", { name: new RegExp(`^${POSITION.replace(/[()]/g, "\\$&")}`) }).click();
    await expect(complaints).toContainText(/жалоб за полгода: 1 из \d+ приглашений \(не та роль — 1\)/);
    await dialog.getByRole("link", { name: "Профиль компании" }).click();
    await expect(page).toHaveURL(/\/candidate\/companies\/[\w-]+$/);
    await expect(page.getByRole("main").getByRole("listitem").filter({ hasText: /Жалобы кандидатов\./ }))
      .toContainText(/жалоб за полгода: 1 из/);
  });

  await test.step("работодатель: приглашение отклонено, причина видна, комментарий — нет", async () => {
    const ctx = await newPersonaContext(browser);
    const emp = await ctx.newPage();
    await juryEnter(emp, "employer");
    await openSection(emp, "Приглашения", /\/employer\/invitations$/);
    const inv = emp.getByRole("main").locator("article").filter({ has: emp.getByText(POSITION, { exact: true }) });
    await expect(inv).toHaveCount(1);
    await expect(inv.getByText("Отклонено", { exact: true }).first()).toBeVisible();
    await expect(inv).toContainText("Жалоба кандидата: не та роль.");
    await expect(inv).not.toContainText(COMMENT);
    await ctx.close();
  });
});
