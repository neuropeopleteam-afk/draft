/**
 * Второй фактор входа (И17): персона «Федерация (ФСП)» подключает приложение-аутентификатор в разделе
 * «Безопасность входа» (QR, ручной ключ, первый код, резервные коды), проверяет код (повтор того же кода
 * не принимается), выходит — и вход в один клик под этой персоной спрашивает код на /login/2fa; затем вход
 * резервным кодом (одноразовый) и отключение. Другие персоны песочницы второй фактор не трогает.
 * Коды считаются здесь же по RFC 6238 (HMAC-SHA1, 30 с), поэтому шаги берутся соседними (окно ±1): ждать 30 с не нужно.
 * Снимки экрана (1440 и 390 px) — в E2E_SHOTS_DIR/twofa (по умолчанию reports/twofa).
 */
import { createHmac } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const DIR = join(process.env.E2E_SHOTS_DIR || "reports", "twofa");
mkdirSync(DIR, { recursive: true });

/* ---------------------------------------------------------------- TOTP (RFC 6238) на node:crypto */
function base32Decode(s: string): Buffer {
  const abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0, value = 0;
  const out: number[] = [];
  for (const ch of s.replace(/[\s=-]/g, "").toUpperCase()) {
    const v = abc.indexOf(ch);
    if (v < 0) throw new Error(`base32: символ ${ch}`);
    value = (value << 5) | v; bits += 5;
    if (bits >= 8) { out.push((value >>> (bits - 8)) & 0xff); bits -= 8; }
  }
  return Buffer.from(out);
}
function hotp(secret: string, counter: number): string {
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", base32Decode(secret)).update(msg).digest();
  const o = h[h.length - 1] & 0x0f;
  const code = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(code % 1_000_000).padStart(6, "0");
}
const step = () => Math.floor(Date.now() / 1000 / 30);
/** Код для шага «сейчас + offset»: сервер принимает окно ±1 шаг и не принимает шаг не новее последнего использованного. */
const totp = (secret: string, offset = 0) => hotp(secret, step() + offset);

async function shot(page: Page, name: string): Promise<void> {
  const file = join(DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}

test.describe.configure({ mode: "serial" });

test("ФСП: подключение второго фактора, проверка кода, повтор кода не принимается", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await juryEnter(page, "fsp");
  await openSection(page, "Безопасность входа", /\/fsp\/security$/);
  await expect(page.getByRole("heading", { level: 1, name: "Безопасность входа" })).toBeVisible();
  const state = page.getByTestId("twofa-state");
  await expect(state).toHaveText(/не подключён/);
  // честная пометка о демо-песочнице
  await expect(page.getByText(/в демо-песочнице второй фактор отключён/)).toBeVisible();
  await shot(page, "01-settings-off-1440");

  await page.getByTestId("twofa-enable").click();
  await expect(page.getByTestId("twofa-qr")).toBeVisible();
  await page.getByRole("button", { name: /ввести ключ вручную/i }).click();
  const secret = (await page.getByTestId("twofa-secret").innerText()).replace(/\s+/g, "");
  expect(secret, "ключ base32 из 32 символов").toMatch(/^[A-Z2-7]{32}$/);
  await shot(page, "02-enroll-qr-1440");

  // первый код — предыдущий шаг (окно ±1): следующие проверки берут шаг «сейчас» и «сейчас + 1»
  await page.getByLabel("Первый код").fill(totp(secret, -1));
  await page.getByRole("button", { name: "Подключить", exact: true }).click();
  const codes = page.getByTestId("twofa-recovery").getByRole("listitem");
  await expect(codes).toHaveCount(10);
  const recovery = await codes.allInnerTexts();
  for (const c of recovery) expect(c).toMatch(/^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/);
  await shot(page, "03-recovery-codes-1440");
  await page.getByLabel(/Я сохранил резервные коды/).check();
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(state).toHaveText(/включён/);
  await expect(page.getByTestId("twofa-recovery-left")).toHaveText(/10 из 10/);

  // проверка кода: верный принимается, тот же — нет (защита от повтора)
  const now = totp(secret, 0);
  await page.getByLabel("Код из приложения").fill(now);
  await page.getByTestId("twofa-check").click();
  await expect(page.getByText(/Код верный/)).toBeVisible();
  await page.getByLabel("Код из приложения").fill(now);
  await page.getByTestId("twofa-check").click();
  await expect(page.getByText(/уже использован/)).toBeVisible();
  await shot(page, "04-settings-on-1440");

  // коды и ключ — для следующих тестов этого прогона
  process.env.TWOFA_SECRET = secret;
  process.env.TWOFA_RECOVERY = recovery.join(",");
});

test("ФСП: вход в один клик спрашивает код; резервный код одноразовый; 390 px без горизонтальной прокрутки", async ({ page }) => {
  const secret = process.env.TWOFA_SECRET!;
  const recovery = process.env.TWOFA_RECOVERY!.split(",");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("section#jury").getByRole("button", { name: /^Войти как:?\s*Федерация/ }).click();
  await expect(page).toHaveURL(/\/login\/2fa$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Код из приложения" })).toBeVisible();
  await expect(page.getByText(/демо-учётка жюри с включённым вторым фактором/)).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width, "390 px: без горизонтальной прокрутки").toBeLessThanOrEqual(391);
  await shot(page, "05-login-code-390");

  // неверный код — ошибка, остаёмся на экране кода
  await page.getByLabel("Код из приложения").fill("000000");
  await page.getByTestId("twofa-login-submit").click();
  await expect(page.getByText(/Код не подошёл/)).toBeVisible();
  // резервный код — вход; в кабинете осталось 9 кодов
  await page.getByLabel("Код из приложения").fill(recovery[0]);
  await page.getByTestId("twofa-login-submit").click();
  await expect(page).toHaveURL(/\/fsp(\/[a-z]*)?$/, { timeout: 60_000 });
  await page.goto("/fsp/security", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("twofa-state")).toHaveText(/включён/);
  await expect(page.getByTestId("twofa-recovery-left")).toHaveText(/9 из 10/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth), "390 px: раздел без горизонтальной прокрутки").toBeLessThanOrEqual(391);
  await shot(page, "06-settings-on-390");

  // использованный резервный код второй раз не подходит
  await page.getByLabel("Код из приложения").fill(recovery[0]);
  await page.getByTestId("twofa-check").click();
  await expect(page.getByText(/не подошёл или уже использован/)).toBeVisible();

  // другая персона песочницы входит в один клик по-прежнему без кода
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("section#jury").getByRole("button", { name: /^Войти как:?\s*Эксперт/ }).click();
  await expect(page).toHaveURL(/\/expert$/, { timeout: 60_000 });

  // отключение — с кодом (шаг «сейчас + 1»: новее всех использованных)
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("section#jury").getByRole("button", { name: /^Войти как:?\s*Федерация/ }).click();
  await expect(page).toHaveURL(/\/login\/2fa$/, { timeout: 60_000 });
  await page.getByLabel("Код из приложения").fill(totp(secret, 1));
  await page.getByTestId("twofa-login-submit").click();
  await expect(page).toHaveURL(/\/fsp(\/[a-z]*)?$/, { timeout: 60_000 });
  await page.goto("/fsp/security", { waitUntil: "domcontentloaded" });
  await page.getByTestId("twofa-disable").click();
  const dialog = page.getByRole("dialog", { name: "Отключить второй фактор" });
  await dialog.getByLabel("Код из приложения").fill(recovery[1]);
  await dialog.getByRole("button", { name: "Отключить" }).click();
  await expect(page.getByTestId("twofa-state")).toHaveText(/не подключён/);
  await shot(page, "07-settings-disabled-1440");
});
