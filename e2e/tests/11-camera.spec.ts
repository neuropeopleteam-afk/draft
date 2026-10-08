/**
 * И16 «Камера по согласию»: поддельная камера Chromium с кадром лица (fixtures/webcam_face.y4m).
 *  1. Работодатель видит у демо-кандидатов итог камеры рядом с достоверностью: Мария — «Камера: включена,
 *     замечаний нет», Илья — «Тест без камеры»; Кабинет ФСП — обезличенный блок камеры.
 *  2. Илья: экран камеры перед тестом → «Включить камеру» (согласие) → превью и «лицо в кадре» → тест с индикатором,
 *     события уходят на сервер по заданиям → результат со своим отчётом камеры → согласие видно в настройках.
 *  3. Браузер не дал доступ к камере (getUserMedia отклонён): честное сообщение, «Продолжить без камеры», тест идёт.
 *
 * Ответы — «вслепую», поэтому грейд обычно не подтверждается и факт T1 не обновляется: работодатель продолжает
 * видеть результат из демо-данных; свежий итог камеры проверяется на экране результата самого кандидата.
 */
import { resolve } from "node:path";
import { expect, newPersonaContext, test } from "../lib/fixtures";
import { apiContext, apiGet, juryToken } from "../lib/stand";
import { runTestBlind } from "../lib/testrun";
import { juryEnter, openSection } from "../lib/ui";

const FACE = resolve(process.cwd(), "fixtures/webcam_face.y4m");

test.use({
  launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", `--use-file-for-fake-video-capture=${FACE}`] },
  permissions: ["camera"],
});
test.describe.configure({ mode: "serial" });

const refs: Record<string, string> = {};

test.beforeAll(async () => {
  const api = await apiContext();
  try {
    for (const p of ["candidate", "candidate_nofsp"] as const) {
      refs[p] = (await apiGet(api, "/me", await juryToken(api, p))).candidate.public_ref;
      expect(refs[p]).toMatch(/^C-[A-Z0-9]+$/);
    }
  } finally {
    await api.dispose();
  }
});

test("работодатель и ФСП: итог камеры у демо-кандидатов", async ({ browser }) => {
  const page = await (await newPersonaContext(browser)).newPage();
  await juryEnter(page, "employer");
  await test.step("Мария — с камерой, замечаний нет; Илья — тест без камеры", async () => {
    for (const [p, title] of [["candidate", "Камера: включена, замечаний нет"], ["candidate_nofsp", "Тест без камеры"]] as const) {
      await page.goto(`/employer/candidates/${refs[p]}`, { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { name: `Кандидат ${refs[p]}` })).toBeVisible();
      const card = page.getByText(/^Достоверность результата:/).first();
      await expect(card).toBeVisible();
      await expect(page.getByTestId("camera-title").first(), p).toHaveText(title);
      // событий по заданиям у работодателя нет — только итог
      await expect(page.getByText(/нет лица в кадре \d/)).toHaveCount(0);
    }
  });
  await test.step("Кабинет ФСП: обезличенный блок камеры", async () => {
    await juryEnter(page, "fsp");
    const block = page.getByTestId("camera-stats");
    await expect(block).toBeVisible({ timeout: 60_000 });
    await expect(block.getByRole("heading", { name: "Камера во время теста" })).toBeVisible();
    await expect(block.getByText(/группы меньше 5 скрыты/)).toBeVisible();
  });
});

test("кандидат: согласие → камера в тесте → свой отчёт камеры", async ({ page }) => {
  await juryEnter(page, "candidate_nofsp");
  await openSection(page, "Опрос и тест", /\/candidate\/assessment$/);
  await expect(page.getByRole("heading", { name: "Тест на грейд" })).toBeVisible();

  await test.step("экран камеры перед тестом: честный текст и две кнопки", async () => {
    await page.getByRole("checkbox", { name: /Я прочитал\(а\), что отслеживается во время теста/ }).check();
    await page.getByRole("button", { name: /^Начать тест$/ }).click();
    await expect(page.getByRole("heading", { name: "Камера во время теста" })).toBeVisible();
    const main = page.getByRole("main");
    for (const t of ["Что делает камера", "Что сохраняется", "Кто это видит"]) await expect(main.getByText(t, { exact: true })).toBeVisible();
    await expect(main.getByText(/не биометрическая идентификация/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Пройти без камеры" })).toBeVisible();
    // сессии теста ещё нет: на экран камеры попадаем до выдачи первого задания
    await expect(page).toHaveURL(/\/candidate\/assessment$/);
  });

  await test.step("включить камеру: согласие записано, превью, «лицо в кадре»", async () => {
    const consent = page.waitForResponse((r) => r.url().endsWith("/api/proctor/consent") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Включить камеру" }).click();
    expect((await consent).status(), "согласие записано").toBe(201);
    await expect(page.getByTestId("camera-state")).toContainText("лицо в кадре", { timeout: 60_000 });
    await expect(page.getByRole("button", { name: "Начать тест с камерой" })).toBeEnabled();
  });

  let eventsPosted = 0;
  page.on("response", (r) => { if (/\/api\/proctor\/sessions\/[^/]+\/events$/.test(r.url()) && r.status() === 200) eventsPosted += 1; });

  await test.step("тест с индикатором камеры", async () => {
    const start = page.waitForResponse((r) => /\/api\/proctor\/sessions\/[^/]+\/start$/.test(r.url()));
    await page.getByRole("button", { name: "Начать тест с камерой" }).click();
    expect((await start).status(), "режим камеры сообщён серверу").toBe(200);
    await expect(page).toHaveURL(/\/candidate\/assessment\/test\/[\w-]+$/);
    const ind = page.getByTestId("camera-indicator");
    await expect(ind).toContainText("лицо в кадре", { timeout: 30_000 });
    await expect(ind.getByRole("button", { name: "Выключить камеру" })).toBeVisible();
    const answered = await runTestBlind(page, async (n) => {
      if (n === 1) await expect(ind).toContainText(/Камера: /);
    });
    test.info().annotations.push({ type: "ответов", description: String(answered) });
    expect(eventsPosted, "наблюдение по заданиям отправлялось на сервер").toBeGreaterThanOrEqual(1);
  });

  await test.step("результат: свой отчёт камеры, события только кандидату", async () => {
    const rep = page.getByTestId("camera-report");
    await expect(rep).toBeVisible();
    await expect(rep).toContainText(/Камера: включена, (замечаний нет|есть замечания)/);
    await expect(rep).toContainText(/Камера наблюдала \d+ заданий/);
    test.info().annotations.push({ type: "итог камеры", description: (await rep.textContent()) ?? "" });
    const events = rep.getByRole("button", { name: /^Мои события: \d+$/ });
    if (await events.isVisible()) {
      await events.click();
      await expect(rep.getByRole("table")).toBeVisible();
      await expect(rep.getByText("Работодателю события не показываются")).toBeVisible();
    } else {
      await expect(rep.getByText("Событий нет: на всех заданиях в кадре было одно лицо.")).toBeVisible();
    }
  });

  await test.step("настройки: согласие на камеру и попытка с режимом", async () => {
    await openSection(page, "Настройки и приватность", /\/candidate\/settings$/);
    const block = page.getByTestId("camera-settings");
    await expect(block).toBeVisible();
    await expect(block.getByText(/^Дано /)).toBeVisible();
    await expect(block.getByText(/Камера: включена/).first()).toBeVisible();
    await expect(block.getByRole("button", { name: "Отозвать" })).toBeVisible();
  });
});

test("кандидат: браузер не дал доступ к камере — честное сообщение, тест без камеры", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
  });
  await juryEnter(page, "candidate_nofsp");
  await openSection(page, "Опрос и тест", /\/candidate\/assessment$/);
  await page.getByRole("checkbox", { name: /Я прочитал\(а\), что отслеживается во время теста/ }).check();
  await page.getByRole("button", { name: /^Начать тест$/ }).click();
  await expect(page.getByRole("heading", { name: "Камера во время теста" })).toBeVisible();
  // согласие уже дано в прошлом сценарии — повторно не спрашивается, сразу запрос камеры
  await page.getByRole("button", { name: "Включить камеру" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Доступ к камере не разрешён в браузере" })).toBeVisible();
  const start = page.waitForResponse((r) => /\/api\/proctor\/sessions\/[^/]+\/start$/.test(r.url()));
  await page.getByRole("button", { name: "Продолжить без камеры" }).click();
  expect(JSON.parse((await start).request().postData() ?? "{}").mode, "режим denied сообщён серверу").toBe("denied");
  await expect(page).toHaveURL(/\/candidate\/assessment\/test\/[\w-]+$/);
  await expect(page.getByRole("button", { name: /^Ответить/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("camera-indicator")).toHaveCount(0);
});
