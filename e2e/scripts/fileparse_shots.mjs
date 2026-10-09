// Ф5: снимки «Загрузить файл вакансии» и «Резюме PDF или DOCX» на 1440 и 390 px, проверка горизонтальной прокрутки.
// Локальный стенд: API на API_URL (uvicorn, DEV_MODE), интерфейс на WEB_URL (vite preview). Запуск:
//   API_URL=http://127.0.0.1:8136 WEB_URL=http://127.0.0.1:5136 OUT=/tmp/fileparse node e2e/scripts/fileparse_shots.mjs
import { chromium } from "playwright";
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const API = process.env.API_URL ?? "http://127.0.0.1:8136";
const WEB = process.env.WEB_URL ?? "http://127.0.0.1:5136";
const OUT = process.env.OUT ?? "/tmp/fileparse";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const EX = join(ROOT, "docs", "examples");

async function account(email, role, extra = {}) {
  const post = (p, b) => fetch(API + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then((r) => r.json());
  const r = await post("/api/auth/register", { email, password: "Passw0rd!x", role, consent_processing: true, ...extra });
  const v = await post("/api/auth/verify-email", { email, code: r.dev_verification_code });
  return v.access_token;
}

async function noHScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
}

const stamp = Date.now();
const emp = await account(`f5-emp-${stamp}@example.com`, "employer", { company_name: "ООО Пример" });
const cand = await account(`f5-cand-${stamp}@example.com`, "candidate");
const result = {};
const browser = await chromium.launch();
for (const [w, h] of [[1440, 900], [390, 844]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, serviceWorkers: "block" });
  const page = await ctx.newPage();
  await page.goto(WEB + "/");
  await page.evaluate((t) => localStorage.setItem("fsp_token", t), emp);
  await page.goto(WEB + "/employer/needs");
  await page.locator('[data-testid="need-file"] input[type=file]').waitFor({ state: "attached" });
  await page.screenshot({ path: join(OUT, `f5_need_file_${w}_before.png`), fullPage: false });
  await page.locator('[data-testid="need-file"] input[type=file]').setInputFiles(join(EX, "vacancy_python_middle.docx"));
  await page.getByText("Откуда взяты требования").waitFor({ timeout: 30000 });
  await page.locator('[data-testid="need-file-note"]').waitFor();
  result[`need_${w}_noHScroll`] = await noHScroll(page);
  result[`need_${w}_note`] = await page.locator('[data-testid="need-file-note"]').innerText();
  result[`need_${w}_textarea_len`] = (await page.locator("#need").inputValue()).length;
  await page.screenshot({ path: join(OUT, `f5_need_file_${w}.png`), fullPage: true });
  // ошибка понятными словами: DOCX с макросами
  await page.getByRole("button", { name: "Изменить текст" }).click();
  const docm = readFileSync(join(OUT, "macro.docm"));
  await page.locator('[data-testid="need-file"] input[type=file]').setInputFiles({ name: "vacancy.docm", mimeType: "application/octet-stream", buffer: docm });
  await page.locator('[data-testid="need-file"] [role=alert]').waitFor({ timeout: 20000 });
  result[`need_${w}_error`] = await page.locator('[data-testid="need-file"] [role=alert]').innerText();
  result[`need_${w}_error_noHScroll`] = await noHScroll(page);
  await page.locator('[data-testid="need-file"]').screenshot({ path: join(OUT, `f5_need_file_${w}_error.png`) });

  await page.evaluate((t) => localStorage.setItem("fsp_token", t), cand);
  await page.goto(WEB + "/candidate/profile");
  const input = page.locator('input[type=file][accept*=".docx"]');
  await input.waitFor({ state: "attached" });
  await input.setInputFiles({ name: "resume.docx", mimeType: "application/octet-stream", buffer: readFileSync(join(OUT, "resume.docx")) });
  await page.getByText("Вырезано до обработки").waitFor({ timeout: 30000 });
  result[`resume_${w}_noHScroll`] = await noHScroll(page);
  await page.getByText("Резюме PDF или DOCX").scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(OUT, `f5_resume_docx_${w}.png`), fullPage: false });
  await ctx.close();
}
await browser.close();
writeFileSync(join(OUT, "f5_shots.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
