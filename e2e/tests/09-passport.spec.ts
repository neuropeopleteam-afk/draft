/**
 * Сценарий жюри, часть 9: подписанный паспорт грейда (backend/app/passport, страница /verify/<id>).
 *
 * Демо-кандидат песочницы уже с категорией: сид прошёл тест настоящим движком банка (finish_session), паспорт
 * выпущен хуком после присвоения категории. Кандидат → «Категория и грейд» → блок «Паспорт грейда» → «Открыть
 * страницу проверки» → та же ссылка в новом контексте без входа и без пароля стенда показывает «Действителен»,
 * без ФИО → скачанный файл паспорта проверяется на странице: подлинный — «Файл подлинный», с изменённым грейдом —
 * «Подпись не сходится» → работодатель видит паспорт в карточке кандидата → кандидат отзывает ссылку (страница —
 * «Отозван») и выпускает новую.
 *
 * Пароль стенда: на fsp.neuropeople.pro страница /verify/<id> открывается без базовой авторизации только после
 * фрагмента nginx infra/nginx/fsp.neuropeople.pro.passport.conf. Если он не применён, это отмечается как ошибка
 * продукта (productIssue; E2E_STRICT=1 — валит тест), а проверка страницы идёт с паролем, чтобы остальное
 * проверялось. /verify без слэша (подтверждение почты) на стенде обязан оставаться под паролем.
 */
import { readFile } from "node:fs/promises";
import { request, type Page } from "@playwright/test";
import { expect, newPersonaContext, productIssue, test } from "../lib/fixtures";
import { apiContext, apiGet, BASE_URL, juryToken } from "../lib/stand";
import { juryEnter, openSection } from "../lib/ui";

const ID = /\/verify\/([A-Za-z0-9_-]{8,32})$/;

test.describe.configure({ mode: "serial" });

let ref = "";
let fullName = "";
let pii: string[] = [];  // ФИО по частям, телефон, telegram демо-кандидата — их не должно быть в паспорте

test.beforeAll(async () => {
  const api = await apiContext();
  try {
    const me = await apiGet(api, "/me", await juryToken(api, "candidate"));
    ref = me.candidate.public_ref;
    fullName = me.candidate.full_name ?? "";
    pii = [fullName, ...fullName.split(" "), me.candidate.phone, me.candidate.telegram].filter((x): x is string => !!x && x.length > 2);
    expect(ref).toMatch(/^C-[A-Z0-9]+$/);
  } finally {
    await api.dispose();
  }
});

/** Блок «Паспорт грейда» на экране «Категория и грейд» и id действующего паспорта из ссылки на проверку. */
async function passportBlock(page: Page) {
  const block = page.getByRole("region", { name: "Паспорт грейда" });
  await expect(block).toBeVisible();
  const link = block.getByRole("link", { name: "Открыть страницу проверки" });
  await expect(link).toHaveAttribute("href", ID);
  const id = ID.exec((await link.getAttribute("href")) ?? "")![1];
  return { block, link, id };
}

test("паспорт грейда: кандидат делится ссылкой, публичная проверка, подделка, карточка работодателя, отзыв", async ({ page, browser }) => {
  await juryEnter(page, "candidate");
  await openSection(page, "Категория и грейд", /\/candidate\/category$/);
  const { block, link, id } = await passportBlock(page);

  await test.step("кабинет кандидата: паспорт выпущен после категории, действителен", async () => {
    await expect(block.getByText("Действителен", { exact: true })).toBeVisible();
    await expect(block.getByRole("button", { name: "Поделиться паспортом" })).toBeVisible();
    await expect(block.getByRole("img", { name: "QR-код ссылки на проверку паспорта" })).toBeVisible();
    await expect(block).toContainText(`/verify/${id}`);
    // ссылка открывает страницу проверки в новой вкладке
    const popup = page.context().waitForEvent("page");
    await link.click();
    const tab = await popup;
    await expect(tab.getByRole("heading", { level: 1 })).toHaveText("Действителен");
    await tab.close();
  });

  // Публичная проверка: без входа (новый контекст без токена и песочницы) и без пароля стенда
  const anonApi = await request.newContext({ baseURL: BASE_URL, httpCredentials: undefined });
  let closed = false;
  await test.step("без пароля стенда: /verify/<id> открыт, /verify (почта) — нет, API паспорта публичный", async () => {
    const r = await anonApi.get(`/verify/${id}`);
    closed = r.status() === 401;
    await productIssue("страница /verify/<id> закрыта паролем стенда: не применён фрагмент nginx " +
      "infra/nginx/fsp.neuropeople.pro.passport.conf", async () => closed);
    if (!closed) expect(r.status(), "страница проверки без пароля").toBe(200);
    if (process.env.E2E_BASIC_USER) {
      expect((await anonApi.get("/verify")).status(), "подтверждение почты /verify остаётся под паролем стенда").toBe(401);
    }
    const api = await anonApi.get(`/api/passport/${id}`);
    expect(api.status()).toBe(200);
    const body = await api.json();
    expect(body.status.state).toBe("valid");
    expect(body.passport.subject).toEqual({ public_ref: ref });
    for (const x of pii) expect(body.document, "ФИО и контакты в подписанном документе").not.toContain(x);
    expect((await anonApi.get("/api/passport/keys")).status()).toBe(200);
  });

  const anonCtx = await browser.newContext(closed ? {} : { httpCredentials: undefined });
  const anon = await anonCtx.newPage();
  await test.step("публичная страница: «Действителен», состав без ФИО и контактов", async () => {
    await anon.goto(`/verify/${id}`);
    await expect(anon.getByRole("heading", { level: 1 })).toHaveText("Действителен");
    await expect(anon.getByText(/подпись Ed25519 верна/)).toBeVisible();
    await expect(anon.getByText(`Кандидат ${ref} · обезличенный идентификатор, без ФИО и контактов`)).toBeVisible();
    await expect(anon.getByRole("heading", { name: /Навыки, подтверждённые заданиями теста/ })).toBeVisible();
    await expect(anon.getByRole("heading", { name: /Достижения ФСП, подтверждённые реестром/ })).toBeVisible();
    await expect(anon.getByRole("link", { name: "Методика и проверка качества теста" })).toBeVisible();
    for (const x of pii) await expect(anon.locator("body")).not.toContainText(x);
    // проводник жюри — только для жюри: у внешнего посетителя его нет
    await expect(anon.getByRole("complementary", { name: "Проводник для экспертов жюри" })).toHaveCount(0);
  });

  await test.step("файл паспорта: подлинный — «Файл подлинный», изменённый грейд — «Подпись не сходится»", async () => {
    const dl = anon.waitForEvent("download");
    await anon.getByRole("button", { name: "Скачать файл паспорта" }).click();
    const file = await dl;
    expect(file.suggestedFilename()).toBe(`passport-${id}.json`);
    const doc = JSON.parse(await readFile(await file.path(), "utf8"));
    expect(doc.passport.id).toBe(id);
    const input = anon.getByLabel("Файл паспорта для проверки");
    await input.setInputFiles({ name: "passport.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
    await expect(anon.getByRole("status").filter({ hasText: "Файл подлинный" })).toBeVisible();
    doc.passport.category.grade = doc.passport.category.grade === "senior" ? "middle" : "senior";
    await input.setInputFiles({ name: "passport.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(doc)) });
    await expect(anon.getByRole("alert").filter({ hasText: "Подпись не сходится" })).toBeVisible();
  });

  await test.step("работодатель: паспорт в карточке кандидата ведёт на ту же проверку", async () => {
    const ctx = await newPersonaContext(browser);
    const emp = await ctx.newPage();
    await juryEnter(emp, "employer");
    await emp.goto(`/employer/candidates/${ref}`);
    const badge = emp.getByRole("region", { name: "Подписанный паспорт грейда" });
    await expect(badge.getByText("Действителен", { exact: true })).toBeVisible();
    await expect(badge.getByRole("link", { name: "Проверить паспорт" })).toHaveAttribute("href", `/verify/${id}`);
    await ctx.close();
  });

  await test.step("кандидат отзывает ссылку: страница — «Отозван»; новая ссылка — «Действителен»", async () => {
    page.once("dialog", (d) => void d.accept());
    await block.getByRole("button", { name: "Отозвать ссылку" }).click();
    await expect(block).toContainText("Вы отозвали ссылку.");
    await anon.reload();
    await expect(anon.getByRole("heading", { level: 1 })).toHaveText("Отозван");
    await expect(anon.getByText(/ссылку отозвал сам кандидат/)).toBeVisible();
    await block.getByRole("button", { name: "Выпустить новую ссылку" }).click();
    const again = await passportBlock(page);
    expect(again.id, "новая ссылка").not.toBe(id);
    await anon.goto(`/verify/${again.id}`);
    await expect(anon.getByRole("heading", { level: 1 })).toHaveText("Действителен");
  });

  await anonCtx.close();
  await anonApi.dispose();
});
