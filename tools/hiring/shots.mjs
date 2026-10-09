// Снимки найма (Н8): 1440 и 390, проверка горизонтальной прокрутки. Своя песочница жюри на локальном стенде :5134.
import { chromium } from "../../e2e/node_modules/playwright/index.mjs";
const base = process.env.HIRING_QA_URL || "http://127.0.0.1:5134";
const out = process.env.OUT || "/tmp/hiring/shots";
const browser = await chromium.launch({ headless: true, args: ["--lang=ru-RU"] });
const report = [];
async function api(path, body, token) {
  const r = await fetch(`${base}/api${path}`, { method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
}
async function until(ok, ms = 15000) {  // ждём состояния на сервере, а не текста на экране
  for (const t0 = Date.now(); Date.now() - t0 < ms; await new Promise((r) => setTimeout(r, 300))) if (await ok()) return;
  throw new Error("состояние не наступило");
}
async function pageAs(token, sid) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "ru-RU", timezoneId: "Europe/Moscow" });
  await ctx.addInitScript(([t, s]) => { localStorage.setItem("fsp_token", t); localStorage.setItem("jury_scenario", s);
    localStorage.setItem("jury_guide_hidden", "1"); }, [token, sid]);
  const p = await ctx.newPage(); p.setDefaultTimeout(15000);
  p.on("pageerror", (e) => report.push(`pageerror: ${e}`));
  return p;
}
async function snap(p, name, focus) {
  for (const w of [1440, 390]) {
    await p.setViewportSize({ width: w, height: w === 390 ? 844 : 1000 });
    await p.waitForTimeout(300);
    if (focus) await focus(w).evaluate((el) => el.scrollIntoView({ block: "start", behavior: "instant" }));
    await p.evaluate(() => window.scrollBy({ top: -12, behavior: "instant" }));
    await p.waitForTimeout(200);
    const d = await p.evaluate(() => ({ w: innerWidth, sw: document.documentElement.scrollWidth }));
    report.push(`${name}-${w}: scrollWidth ${d.sw} / ${d.w} ${d.sw <= d.w ? "ok" : "ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"}`);
    await p.screenshot({ path: `${out}/${name}-${w}.png` });
  }
  await p.setViewportSize({ width: 1440, height: 1000 });
}
try {
  const e = await api("/jury/login", { persona: "employer", scenario: "new" });
  const sid = e.scenario, te = e.access_token;
  const tc = (await api("/jury/login", { persona: "candidate_nofsp", scenario: sid })).access_token;
  const inv = (await api("/candidate/invitations", null, tc)).find((i) => i.position_title === "Backend-разработчик (платежи)");
  await api(`/candidate/invitations/${inv.id}/accept`, {}, tc);
  await new Promise((r) => setTimeout(r, 1500));
  // 1. работодатель: блок «Найм» у принятого приглашения, форма слотов
  const pe = await pageAs(te, sid);
  await pe.goto(`${base}/employer/invitations`);
  const card = () => pe.locator("article", { hasText: "Backend-разработчик (платежи)" }).first();
  await card().getByRole("button", { name: "Предложить время собеседования" }).click();
  await card().getByRole("button", { name: "Предложить кандидату" }).waitFor();
  await snap(pe, "1-employer-slots", () => card().locator("section[aria-label='Найм']"));
  await card().getByRole("button", { name: "Предложить кандидату" }).click();
  await card().getByText("ждём, какой слот выберет кандидат").waitFor();
  // 2. кандидат: выбор слота
  const pc = await pageAs(tc, sid);
  await pc.goto(`${base}/candidate/invitations`);
  await pc.getByRole("button", { name: /Backend-разработчик \(платежи\)/ }).first().click();
  const modal = () => pc.getByRole("dialog");
  await modal().getByRole("button", { name: "Подтвердить время" }).waitFor();
  await modal().getByRole("radio").first().check();
  await snap(pc, "2-candidate-slots", () => modal().locator("section[aria-label='Найм']"));
  await modal().getByRole("button", { name: "Подтвердить время" }).click();
  await until(async () => (await api(`/candidate/invitations/${inv.id}/hiring`, null, tc)).interview?.status === "scheduled");
  // 3. работодатель: «прошло» и оффер (готовые значения) — кликами
  await pe.reload();
  await card().getByRole("button", { name: "Собеседование прошло" }).click();
  await card().getByRole("button", { name: "Отправить оффер" }).click();
  await card().locator("form, div").getByRole("button", { name: /^Отправить оффер$/ }).last().click();
  await card().getByText(/^Оффер отправлен:/).waitFor();
  // 4. кандидат: оффер
  await pc.reload();
  await pc.getByRole("button", { name: /Backend-разработчик \(платежи\)/ }).first().click();
  await modal().getByRole("button", { name: "Принять оффер" }).waitFor();
  await snap(pc, "3-candidate-offer", () => modal().locator("section[aria-label='Найм']"));
  await modal().getByRole("button", { name: "Принять оффер" }).click();
  await modal().getByText(/Вы приняли оффер/).first().waitFor();
  await until(async () => (await api(`/candidate/invitations/${inv.id}/hiring`, null, tc)).offer?.status === "accepted");
  // 5. работодатель: «Вышел на работу» → этап в «Потоке» и обратно
  await pe.reload();
  await card().getByRole("button", { name: "Вышел на работу" }).click();
  await card().getByText(/Передано:\s*«?Поток»? · этап «Вышел на работу»/).first().waitFor({ timeout: 20000 });
  await pe.reload();
  await card().getByText(/Передано:\s*«?Поток»? · этап «Вышел на работу»/).first().waitFor({ timeout: 20000 });
  await snap(pe, "4-employer-hired", (w) => w === 390 ? card().locator("section[aria-label='Передача в ATS']") : card());
  const st = await api(`/employer/invitations/${inv.id}/hiring`, null, te);
  report.push("ats: " + JSON.stringify(st.ats.map((a) => [a.target, a.status, a.stage_title])));
  const ci = (await api("/candidate/invitations", null, tc)).find((i) => i.id === inv.id);
  report.push("candidate sees: " + JSON.stringify({ hiring: ci.hiring?.stage, ats_stage: ci.ats_stage?.title }));
  const notes = (await api("/notifications", null, tc)).items.filter((n) => n.kind === "hiring").map((n) => n.title);
  report.push("candidate notifications (hiring): " + notes.length + " · " + notes.slice(0, 2).join(" | "));
  const pre = (await api("/employer/invitations", null, te)).find((i) => i.position_title === "Python-разработчик (платёжный шлюз)");
  report.push("seeded interview: " + (pre?.hiring?.line ?? "нет"));
} catch (err) {
  report.push("ОШИБКА: " + String(err).slice(0, 600));
} finally {
  console.log(report.join("\n"));
  await browser.close();
}
