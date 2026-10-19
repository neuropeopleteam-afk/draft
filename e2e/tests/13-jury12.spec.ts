/**
 * Я9 «Проверка за 12 минут»: короткий режим проводника жюри (большой справочник остаётся).
 * 1440: /jury/go — выбор режима → своя потребность из заготовки (с отрицанием) → первые три → сравнение → приглашение
 * с вилкой демо-кандидату своей копии → ответ за него → экспресс-тест помечен «краткий режим жюри» → категория →
 * доказательства → справочник. У каждого шага — «Проверяет» и «Критерий ТЗ», таймер-ориентир и прогресс.
 * 390: проводник не перекрывает действия шага (поле, «Разобрать требования», «Сохранить…», «Пригласить»), кнопки
 * проводника видны без прокрутки панели, горизонтальной прокрутки нет; свёрнутый — в шапке.
 * Флаг устной защиты (Я15, /api/meta interview.enabled): шаг «по желанию» перед доказательствами, в план 12 минут не
 * входит: кандидатом — «Две попытки рядом» (панель Я15), «Как видит работодатель» — карточка Марии; без флага шагов 8.
 */
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter } from "../lib/ui";

const PY = "Ищем Python-разработчика middle: FastAPI, PostgreSQL, Docker. Django не нужен, PHP не нужен. Желательно Redis. Удалённо, 200–260 тыс. ₽";
const POSITION = "Python-разработчик (Я9, 12 минут)";

async function notCovered(el: Locator): Promise<boolean> {
  await el.scrollIntoViewIfNeeded();
  return el.evaluate(async (b) => {
    // без плавной прокрутки (html scroll-behavior: smooth): иначе координаты читаются до конца анимации
    b.scrollIntoView({ block: "center", behavior: "instant" as ScrollBehavior });
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    const r = b.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!hit && (hit === b || b.contains(hit));
  });
}
/** Элемент целиком в окне и не перекрыт (без прокрутки страницы). */
async function onScreen(el: Locator): Promise<boolean> {
  return el.evaluate((b) => {
    const r = b.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight || r.left < 0 || r.right > window.innerWidth) return false;
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!hit && (hit === b || b.contains(hit));
  });
}
const noHScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const guideOf = (page: Page) => page.getByRole("complementary", { name: "Проводник для экспертов жюри" });

async function expectStep(page: Page, n: number, title: string): Promise<void> {
  const g = guideOf(page);
  await expect(g.getByText(new RegExp(`^Шаг ${n} из 8`))).toBeVisible({ timeout: 30_000 });
  await expect(g.getByText(title, { exact: true })).toBeVisible();
  await expect(g.getByText(/^Проверяет:/).first()).toBeVisible();
  await expect(g.getByText(/^Критерий ТЗ \d\./).first()).toBeVisible();
  expect(await noHScroll(page), `шаг ${n}: без горизонтальной прокрутки`).toBe(true);
}
async function next(page: Page, title: string): Promise<void> {
  await guideOf(page).getByRole("button", { name: `Дальше: ${title}` }).click();
}

/** /jury/go → «Проверка за 12 минут» → «Потребности» под работодателем своей копии. */
async function startQuick(page: Page): Promise<void> {
  await page.goto("/jury/go");
  await expect(page.getByRole("heading", { level: 1, name: "Как будете проверять?" })).toBeVisible();
  const quick = page.getByTestId("choice-quick");
  await expect(quick.getByRole("heading", { name: "Проверка за 12 минут" })).toBeVisible();
  await expect(quick.locator("ol > li")).toHaveCount(8);
  await expect(page.getByTestId("choice-full")).toContainText("до 80 минут");
  expect(await noHScroll(page), "выбор режима без горизонтальной прокрутки").toBe(true);
  await quick.getByRole("button", { name: "Начать: войти как работодатель" }).click();
  await expect(page).toHaveURL(/\/employer\/needs$/, { timeout: 60_000 });
  const g = guideOf(page);
  await expect(g).toBeVisible();
  await expect(g.getByRole("button", { name: "Проверка за 12 минут" })).toHaveAttribute("aria-pressed", "true");
  await expect(g.getByTestId("quick-timer")).toContainText(/Прошло \d+:\d\d · план 2\sмин из 12/);
}

test("1440: проверка за 12 минут — от своей потребности до доказательств", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await startQuick(page);
  await expectStep(page, 1, "Своя потребность своими словами");
  const g = guideOf(page);

  await test.step("1. заготовка с отрицанием → разбор с цитатами → сохранение", async () => {
    await expect(g.getByTestId("quick-presets").getByRole("button")).toHaveCount(3);
    await expect(g.getByText(/Или напишите свою/)).toBeVisible();
    await g.getByRole("button", { name: "Python, с отрицанием" }).click();
    const field = page.getByLabel("Кого вы ищете");
    await expect(field).toHaveValue(PY);
    await page.getByRole("button", { name: "Разобрать требования" }).click();
    const main = page.locator("main");
    await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible({ timeout: 60_000 });
    // отрицания — в «исключено», с цитатой из текста
    const excluded = main.locator("li").filter({ hasText: /^Исключено по тексту:/ });
    await expect(excluded).toContainText("Django («Django не нужен»)");
    await expect(excluded).toContainText("PHP («PHP не нужен»)");
    await main.getByRole("button", { name: "Подтвердить все" }).click();
    await page.getByRole("button", { name: "Сохранить и показать подборку" }).click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
  });

  await test.step("2. первые три кандидата и объяснения", async () => {
    await expectStep(page, 2, "Первые три кандидата и почему они");
    // компактная подборка: доказательства — по «Подробнее» первой карточки (на широком экране — панель справа), как в 02
    const firstCard = page.locator('[data-testid="candidate-card"]').first();
    await expect(firstCard).toBeVisible({ timeout: 60_000 });
    if (!(await page.getByTestId("side-details").isVisible())) await firstCard.getByRole("button", { name: /^Подробнее/ }).click();
    await expect(page.locator("details").filter({ has: page.getByText("Почему в подборке") }).first()).toBeVisible({ timeout: 60_000 });
    await next(page, "Сравнение трёх рядом");
  });

  await test.step("3. сравнение трёх рядом", async () => {
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+\/compare/);
    // аудит №1: на сравнении проводник свёрнут (не сужает таблицу) — разворачиваем
    await expect(page.getByTestId("guide-continue")).toHaveText("Продолжить проверку: шаг 3 из 8");
    await page.getByTestId("guide-continue").click();
    await expectStep(page, 3, "Сравнение трёх рядом");
    await expect(page.getByRole("heading", { name: "Сравнение кандидатов" })).toBeVisible({ timeout: 60_000 });
    await next(page, "Приглашение с зарплатой");
  });

  let own = false;
  await test.step("4. приглашение с вилкой демо-кандидату своей копии", async () => {
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/);
    await expectStep(page, 4, "Приглашение с зарплатой");
    const hint = g.getByTestId("quick-invite-hint");
    await expect(hint).toBeVisible({ timeout: 30_000 });
    const ref = /кандидата (C-[A-Z0-9]+)/.exec((await hint.textContent()) ?? "")?.[1];
    // демо-кандидат своей копии — по подсказке; нет такого (в той же песочнице его уже пригласил 02, период тишины) —
    // первый из подборки, кому приглашение уходит (у кого период тишины — ошибка в окне, берём следующего)
    const cards = ref ? page.locator("article").filter({ has: page.getByText(`Кандидат ${ref}`, { exact: true }) })
      : page.locator("article").filter({ has: page.getByRole("button", { name: "Пригласить", exact: true }) });
    let sent = false;
    for (let i = 0; i < (ref ? 1 : 5) && !sent; i++) {
      await cards.nth(i).getByRole("button", { name: "Пригласить", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: /^Приглашение кандидату C-/ });  // Ф6 (Н9): окно из подборки
      await expect(dialog).toBeVisible();
      await dialog.locator("#it").fill(POSITION);
      await dialog.locator("#idesc").fill("Команда платежей: FastAPI, PostgreSQL, Docker. Удалённо. Проверка e2e Я9.");
      await dialog.locator("#ic").fill("hr@jury.example.com");
      await dialog.locator("#sf").fill("200000");
      await dialog.locator("#st").fill("260000");
      const send = dialog.getByRole("button", { name: "Отправить приглашение" });
      // кнопка активна, когда карточка кандидата загружена; не активна совсем (ограничения оффера) — следующий
      const ready = await expect(send).toBeEnabled({ timeout: 15_000 }).then(() => true, (e) => { if (ref) throw e; return false; });
      if (!ready) { await dialog.getByRole("button", { name: "Закрыть" }).first().click(); await expect(dialog).toBeHidden(); continue; }
      await send.click();
      const err = dialog.getByRole("alert");
      await expect.poll(async () => (await dialog.isHidden()) ? "sent" : (await err.count()) ? "error" : "wait",
        { timeout: 30_000, message: "приглашение ушло или показана причина" }).not.toBe("wait");
      sent = await dialog.isHidden();
      if (!sent) {
        expect(ref, `приглашение своему демо-кандидату ${ref} не ушло: ${await err.first().textContent()}`).toBeUndefined();
        await dialog.getByRole("button", { name: "Закрыть" }).first().click();
        await expect(dialog).toBeHidden();
      }
    }
    expect(sent, "приглашение с вилкой отправлено").toBe(true);
    // аудит №2: карточка — «Приглашён ✓», шаг в проводнике отмечен
    await expect(page.getByTestId("card-invited").first()).toHaveText("Приглашён ✓");
    await expect(hint).toContainText("✓ Приглашение отправлено", { timeout: 30_000 });
    own = !!ref;
  });

  await test.step("5. ответ кандидата — за того, кого пригласили", async () => {
    await next(page, "Ответ кандидата");
    await expect(page).toHaveURL(/\/candidate\/invitations/, { timeout: 60_000 });
    await expectStep(page, 5, "Ответ кандидата");
    await expect(g.getByTestId("quick-answer-hint")).toContainText(own ? "Отвечаете на своё приглашение" : "Илье Сергееву");
    if (own) {
      await page.getByRole("button", { name: new RegExp(POSITION.replace(/[()]/g, "\\$&")) }).click();
      const dialog = page.getByRole("dialog", { name: POSITION });
      await expect(dialog).toContainText(/200\s?000.*260\s?000/);
      await dialog.getByRole("button", { name: "Принять и открыть контакты" }).click();
      await expect(dialog.getByRole("status").filter({ hasText: "Вы приняли приглашение" })).toBeVisible();
      await dialog.getByRole("button", { name: "Закрыть" }).click();
      await expect(dialog).toBeHidden();
    }
  });

  await test.step("6. экспресс-тест — краткий режим жюри, не полный", async () => {
    await next(page, "Экспресс-тест · краткий режим жюри");
    await expect(page).toHaveURL(/\/candidate\/express/, { timeout: 60_000 });
    await expectStep(page, 6, "Экспресс-тест · краткий режим жюри");
    await expect(g).toContainText("не полный тест");
    const choice = page.getByTestId("mode-choice");
    await expect(choice.getByTestId("jury-brief")).toHaveText("Краткий режим жюри");
    await expect(choice).toContainText("Не полный тест (до 80 минут)");
    expect(await notCovered(page.getByRole("button", { name: "Начать экспресс-тест" })), "«Начать экспресс-тест» не под проводником").toBe(true);
  });

  await test.step("7–8. категория и доказательства одной кнопкой", async () => {
    await next(page, "Результат и категория");
    await expect(page).toHaveURL(/\/candidate\/category/);
    await expectStep(page, 7, "Результат и категория");
    await next(page, "Доказательства одной кнопкой");
    await expect(page).toHaveURL(/\/criteria/);
    await expectStep(page, 8, "Доказательства одной кнопкой");
    await expect(page.getByRole("heading", { level: 1, name: "Проверьте нас по критериям ТЗ" })).toBeVisible();
    await g.getByRole("link", { name: "Метрики — /validation" }).click();
    await expect(page).toHaveURL(/\/validation/);
    await expect(page.getByRole("heading", { level: 1, name: "Как мы проверяем себя" })).toBeVisible();
    await expectStep(page, 8, "Доказательства одной кнопкой");
  });

  await test.step("справочник остаётся: переключатель в шапке", async () => {
    // С2 №5: «Готово» — короткий итог, справочник — с шага 1
    await g.getByRole("button", { name: "Готово", exact: true }).click();
    await expect(g.getByTestId("quick-done")).toContainText(/Проверка за 12 минут пройдена за \d+:\d\d · 8 шагов/);
    await g.getByRole("button", { name: "Справочник с шага 1" }).click();
    await expect(g.getByRole("button", { name: "Справочник" })).toHaveAttribute("aria-pressed", "true");
    await expect(g.getByText(/^Проводник жюри · шаг 1 из \d+$/)).toBeVisible();
    await g.getByRole("button", { name: "Проверка за 12 минут" }).click();
    await expectStep(page, 8, "Доказательства одной кнопкой");
  });
});

test("390: проводник «12 минут» не перекрывает действия и помещается", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await startQuick(page);
  const g = guideOf(page);
  await expectStep(page, 1, "Своя потребность своими словами");
  // кнопки проводника — на виду без прокрутки панели (липкий низ)
  expect(await onScreen(g.getByRole("button", { name: "Назад" })), "действия проводника видны").toBe(true);
  const box = await g.boundingBox();
  expect(box!.height, "проводник не выше 40 % экрана").toBeLessThanOrEqual(844 * 0.4);

  await g.getByRole("button", { name: "Go и ClickHouse, Казань" }).click();
  await expect(page.getByLabel("Кого вы ищете")).toHaveValue(/ClickHouse/);
  expect(await notCovered(page.getByLabel("Кого вы ищете")), "поле не под проводником").toBe(true);
  const parse = page.getByRole("button", { name: "Разобрать требования" });
  expect(await notCovered(parse), "«Разобрать требования» не под проводником").toBe(true);
  await parse.click();
  const main = page.locator("main");
  await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible({ timeout: 60_000 });
  // нестандартный стек: Rust — вне справочника, честно отмечен
  await expect(main.getByText("Rust").first()).toBeVisible();
  expect(await noHScroll(page), "разбор без горизонтальной прокрутки").toBe(true);
  const confirmAll = main.getByRole("button", { name: "Подтвердить все" });
  expect(await notCovered(confirmAll), "«Подтвердить все» не под проводником").toBe(true);
  await confirmAll.click();
  const save = page.getByRole("button", { name: "Сохранить и показать подборку" });
  await expect(save).toBeVisible();
  expect(await notCovered(save), "«Сохранить и показать подборку» не под проводником").toBe(true);
  await save.click();
  await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
  await expectStep(page, 2, "Первые три кандидата и почему они");
  const invite = page.getByRole("button", { name: "Пригласить", exact: true }).first();
  await expect(invite).toBeVisible({ timeout: 60_000 });
  expect(await notCovered(invite), "«Пригласить» не под проводником").toBe(true);
  expect(await onScreen(g.getByRole("button", { name: "Дальше: Сравнение трёх рядом" })), "«Дальше» видна").toBe(true);

  await test.step("свёрнутый — в шапке, с номером шага короткого режима", async () => {
    await g.getByRole("button", { name: "Скрыть проводник" }).click();
    const pill = page.getByRole("button", { name: "Показать проводник для жюри" });
    await expect(pill).toBeVisible();
    await expect(pill).toContainText("12 минут · 2/8");
    expect(await pill.evaluate((el) => getComputedStyle(el).position)).toBe("static");
    await pill.click();
    await expect(g).toBeVisible();
  });
});

test("устная защита по флагу (Я15): обычный шаг перед доказательствами, ведёт прямо к панели, 1440 и 390", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  // флаг сервера INTERVIEW_ENABLED по умолчанию выключен — включаем его только в ответе /api/meta этой страницы
  await page.route("**/api/meta", async (route) => {
    const r = await route.fetch();
    await route.fulfill({ response: r, json: { ...(await r.json()), interview: { enabled: true, stub: true, defense_minutes: 3 } } });
  });
  await page.goto("/jury/go");
  const choice = page.getByTestId("choice-quick");
  await expect(choice.locator("ol > li")).toHaveCount(9);
  await expect(choice).toContainText("9 шагов · около 12 минут");
  await expect(choice.locator("ol > li").nth(7)).toContainText("Устная защита ответа");
  await expect(choice.locator("ol > li").nth(7)).not.toContainText("по желанию");
  await expect(choice.locator("ol > li").nth(8)).toContainText("Доказательства одной кнопкой");

  await juryEnter(page, "candidate_new");
  await page.getByRole("button", { name: "Показать проводник для жюри" }).click();
  const g = guideOf(page);
  await expect(g.getByRole("button", { name: "Проверка за 12 минут" })).toHaveAttribute("aria-pressed", "true");
  await page.goto("/candidate/category");
  await expect(g.getByText(/^Шаг 7 из 9/)).toBeVisible({ timeout: 30_000 });
  // FINAL-UX B: устная защита — обычный шаг: «Дальше» ведёт к ней, сразу к раскрытой панели
  await expect(g.getByTestId("quick-optional")).toHaveCount(0);
  // Д2: переход к шагу 8 — явная основная кнопка в теле панели, а не сноска
  await expect(g.getByTestId("quick-defense-next")).toBeVisible();
  await g.getByTestId("quick-to-defense").click();
  // кандидатом «Пройдите тест сами» — «Две попытки рядом», там панель Я15 «Подтвердите авторство ответа»
  await expect(page).toHaveURL(/\/candidate\/attempts\?defense=open#defense$/);
  await expect(g.getByText(/^Шаг 8 из 9 · ≈\s3\sмин/)).toBeVisible();
  await expect(g.getByTestId("quick-live")).toContainText("движок — заглушка");
  // та же ступень глазами работодателя своей копии: карточка Марии Королёвой (вход за работодателя — сам)
  await g.getByTestId("quick-live").getByRole("button", { name: "Как видит работодатель" }).click();
  await expect(page).toHaveURL(/\/employer\/candidates\/C-[A-Z0-9]+/, { timeout: 60_000 });
  await expect(g.getByText(/^Шаг 8 из 9/)).toBeVisible();
  await expect(g.getByText("Устная защита ответа", { exact: true })).toBeVisible();
  await expect(g).toContainText("Грейд не меняет; оценивает модель, не человек");
  await expect(g.getByTestId("quick-timer")).toContainText(/из 12/);
  await expect(g.getByText(/^Проверяет:/)).toBeVisible();
  await expect(g.getByText(/^Критерий ТЗ 2\./)).toBeVisible();

  await test.step("390: шаг устной защиты помещается, кнопки на виду", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);  // ResizeObserver проводника пересчитывает место
    const nextBtn = g.getByRole("button", { name: "Дальше: Доказательства одной кнопкой" });
    expect(await onScreen(nextBtn), "«Дальше» видна без прокрутки панели").toBe(true);
    expect((await g.boundingBox())!.height, "проводник не выше 40 % экрана").toBeLessThanOrEqual(844 * 0.4);
    expect(await noHScroll(page), "без горизонтальной прокрутки").toBe(true);
    await nextBtn.click();
    await expect(page).toHaveURL(/\/criteria/);
    await expect(g.getByText(/^Шаг 9 из 9/)).toBeVisible();
  });
});
