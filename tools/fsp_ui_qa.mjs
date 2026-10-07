// Локальный И6 smoke: настоящий Chromium, обычные клики, отдельная песочница жюри.
import { chromium } from "../e2e/node_modules/playwright/index.mjs";
import { mkdir, writeFile } from "node:fs/promises";

const base = process.env.FSP_QA_URL || "http://127.0.0.1:5106";
const out = process.env.FSP_QA_OUT || "/tmp/fsp2/shots";
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: "chromium" });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage();
page.setDefaultTimeout(12000);
const report = { checks: [], errors: [] };
page.on("pageerror", e => report.errors.push(String(e)));
const check = (name, passed, detail = null) => {
  report.checks.push({ name, passed, detail });
  console.log(name, passed, detail ?? "");
  if (!passed) throw new Error(name);
};
async function snapshot(name, focus = null) {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    if (focus) await focus.scrollIntoViewIfNeeded();
    const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
    check(`${name}-${width}: без прокрутки страницы по горизонтали`, dimensions.scroll <= dimensions.width, dimensions);
    await page.screenshot({ path: `${out}/${name}${width}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
}
async function api(path, data, token) {
  const res = await page.request.fetch(`${base}/api${path}`, {
    method: data ? "POST" : "GET", data,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok()) throw new Error(`${path}: ${res.status()} ${await res.text()}`);
  return res.json();
}
try {
  await page.goto(`${base}/login`);
  await page.getByTestId("button-fsp-login").waitFor();
  check("ФСП ID на входе", await page.getByTestId("button-fsp-login").isVisible());
  await snapshot("login");
  await page.goto(`${base}/register`);
  await page.getByTestId("button-fsp-login").waitFor();
  await snapshot("register");
  await page.getByRole("tab", { name: "Я работодатель", exact: true }).click();
  check("ФСП ID в регистрации работодателя", await page.getByText(/ФСП ID ↔ профиль компании/).isVisible());
  await snapshot("register-employer");
  // Получаем только id собственной песочницы; вход в кабинет — настоящим кликом на главной.
  const candidate = await api("/jury/login", { persona: "candidate", scenario: "new" });
  report.scenario = candidate.scenario;
  await page.evaluate(sid => localStorage.setItem("jury_scenario", sid), candidate.scenario);
  await page.goto(`${base}/`);
  await page.locator("section#jury").getByRole("button", { name: /Войти как.*Кандидат с паспортом/ }).click();
  await page.waitForURL("**/candidate");
  const guide = page.getByRole("button", { name: "Скрыть проводник", exact: true });
  if (await guide.isVisible()) await guide.click();
  const before = await api("/me", null, candidate.access_token);
  report.candidate_ref = before.candidate.public_ref;
  await page.goto(`${base}/candidate/fsp`);
  await page.getByRole("heading", { name: "Паспорт ФСП", exact: true }).waitFor();
  await page.getByTestId("button-fsp-registry-sync").waitFor();
  await snapshot("passport");
  await page.getByTestId("button-fsp-registry-sync").click();
  await page.getByText("Демо: командный чемпионат по продуктовому программированию", { exact: false }).first().waitFor();
  const passport = await api("/me/fsp", null, candidate.access_token);
  check("Импорт командного результата HTTP-мока", passport.achievements.some(a => a.team_result?.place === 1));
  const beforeAge = await api("/me", null, candidate.access_token);
  await snapshot("passport-synced");
  await snapshot("passport-results", page.getByText(/Демо: командный чемпионат по продуктовому программированию/).first());
  await page.goto(`${base}/candidate/profile`);
  await page.getByTestId("select-age-group").selectOption("16-17");
  await page.getByTestId("youth-profile").getByText("Получено согласие родителя или законного представителя на обработку данных", { exact: true }).click();
  await page.getByTestId("button-youth-save").click();
  await page.getByText("Условия сохранены. Возраст не участвует в рейтинге и подборе.", { exact: true }).waitFor();
  const young = await api("/me", null, candidate.access_token);
  check("Возрастная группа и согласие сохранены", young.candidate.age_group === "16-17" && young.candidate.parental_consent);
  check("Смена возраста не меняет рейтинг", beforeAge.candidate.rating_score === young.candidate.rating_score);
  await snapshot("youth");
  const employer = await api("/jury/login", { persona: "employer", scenario: candidate.scenario });
  await page.evaluate(token => localStorage.setItem("fsp_token", token), employer.access_token);
  await page.goto(`${base}/employer/candidates/${before.candidate.public_ref}`);
  await page.getByRole("button", { name: "Пригласить", exact: true }).click();
  await page.getByLabel("Позиция", { exact: true }).fill("Стажёр Python — безопасные условия");
  await page.getByLabel("Суть предложения", { exact: true }).fill("Стажировка в команде разработки, лёгкие задачи под руководством наставника.");
  await page.getByLabel("Как с вами связаться", { exact: true }).fill("hr@example.test");
  const send = page.getByRole("button", { name: "Отправить приглашение", exact: true });
  check("Обычный оффер несовершеннолетнему выключен", await send.isDisabled());
  await page.getByLabel("Формат предложения", { exact: true }).selectOption("internship");
  await page.getByText("Сокращённое рабочее время", { exact: true }).click();
  await page.getByText("Проверю документы и ограничения перед оформлением", { exact: true }).click();
  check("Безопасный оффер доступен", await send.isEnabled());
  await snapshot("invite-youth");
  await snapshot("invite-youth-controls", page.getByLabel("Формат предложения", { exact: true }));
  await send.click();
  await page.getByText("Приглашение отправлено. Кандидат получит письмо; контакты откроются после принятия.", { exact: true }).waitFor();
  check("Безопасный оффер отправлен из UI", true);
  await page.evaluate(token => localStorage.setItem("fsp_token", token), candidate.access_token);
  await page.goto(`${base}/candidate/invitations`);
  await page.getByText("Стажёр Python — безопасные условия", { exact: true }).first().waitFor();
  await page.getByRole("button", { name: /Стажёр Python — безопасные условия/ }).click();
  await page.getByText(/Стажировка · сокращённое рабочее время/).first().waitFor();
  check("Кандидат видит сокращённое время", await page.getByText(/Стажировка · сокращённое рабочее время/).first().isVisible());
  await snapshot("incoming-youth");
  await page.goto(`${base}/candidate/profile`);
  await page.getByTestId("youth-profile").getByText("Получено согласие родителя или законного представителя на обработку данных", { exact: true }).click();
  await page.getByTestId("button-youth-save").click();
  await page.getByText("Условия сохранены. Возраст не участвует в рейтинге и подборе.", { exact: true }).waitFor();
  await page.goto(`${base}/candidate/invitations`);
  await page.getByRole("button", { name: /Стажёр Python — безопасные условия/ }).click();
  await page.getByRole("button", { name: "Принять и открыть контакты", exact: true }).click();
  await page.getByText("Кандидат ещё не отметил согласие родителя или законного представителя", { exact: true }).waitFor();
  check("Отзыв согласия блокирует принятие ранее отправленного оффера", true);
  await snapshot("revoked-consent");
  await page.goto(`${base}/candidate/profile`);
  for (const group of ["14-15", "18+"]) {
    await page.getByTestId("select-age-group").selectOption(group);
    await page.getByTestId("button-youth-save").click();
    await page.getByText("Условия сохранены. Возраст не участвует в рейтинге и подборе.", { exact: true }).waitFor();
    const me = await api("/me", null, candidate.access_token);
    check(`Группа ${group}: сохранение без изменения рейтинга`, me.candidate.age_group === group && me.candidate.rating_score === beforeAge.candidate.rating_score);
    await snapshot(`youth-${group}`, page.getByTestId("youth-profile"));
  }
  await page.goto(`${base}/validation`);
  await page.getByRole("heading", { name: "Рейтинг ФСП: проверка до и после", exact: true }).waitFor();
  await snapshot("validation-fsp", page.getByRole("heading", { name: "Рейтинг ФСП: проверка до и после", exact: true }));
  check("Честное отрицательное различие в метриках", await page.getByText(/Численная потеря не скрыта/).isVisible());
  const demographics = page.locator("section#red-button article").filter({ has: page.getByText("Сменить пол, возраст и имя", { exact: true }) });
  await demographics.getByRole("button", { name: /Запустить/ }).click();
  await demographics.getByRole("status").getByText(/Свойство выполнено/).waitFor();
  check("Красная кнопка: возраст и согласие не меняют подбор", (await demographics.getByRole("status").innerText()).includes("ничего не записано"));
  await snapshot("red-button-youth", demographics);
  check("Нет ошибок JavaScript", report.errors.length === 0, report.errors);
} catch (e) {
  report.failure = String(e);
  console.error(e);
  await page.screenshot({ path: `${out}/failure.png` });
  await writeFile(`${out}/failure.txt`, await page.locator("body").innerText());
  process.exitCode = 1;
} finally {
  await writeFile(`${out}/qa.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
