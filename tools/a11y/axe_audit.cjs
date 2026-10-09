// Аудит доступности ключевых экранов жюри: axe-core (WCAG 2.1 A/AA + best-practice) на 1440 и 390 px.
// npm-пакеты не добавляются: playwright-core берётся из e2e/node_modules, axe.min.js — отдельным файлом и
// подключается в страницу через page.addScriptTag.
//
//   curl -sSL -o /tmp/axe.min.js https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js
//   BASE=http://127.0.0.1:5138 AXE=/tmp/axe.min.js OUT=/tmp/a11y/after node tools/a11y/axe_audit.cjs
//
// APPEND=1 — дописать результаты к прежнему OUT/axe.json (проход частями).
// Итог — OUT/axe.json (по экранам: число нарушений по степеням, правила, примеры узлов) и OUT/axe_summary.md.
// Степени axe: critical, serious, moderate, minor. «Нарушение» = правило × экран (узлы считаются отдельно).
// SHOTS=1 — дополнительно снимки ключевых экранов в OUT/shots. ONLY=landing,selection — только эти экраны.
const path = require("path");
const fs = require("fs");
const ROOT = path.resolve(__dirname, "../..");
const { chromium } = require(path.join(ROOT, "e2e/node_modules/playwright-core"));

const BASE = process.env.BASE || "http://127.0.0.1:5138";
const AXE = process.env.AXE || "/tmp/a11y/axe.min.js";
const OUT = process.env.OUT || "/tmp/a11y/axe";
const SHOTS = process.env.SHOTS === "1";
const ONLY = (process.env.ONLY || "").split(",").filter(Boolean);
const VIEWPORTS = (process.env.VIEWPORTS || "1440x900,390x844").split(",").map((s) => s.split("x").map(Number));
fs.mkdirSync(path.join(OUT, "shots"), { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const IMPACTS = ["critical", "serious", "moderate", "minor"];

async function jreq(p, token, opt = {}) {
  const r = await fetch(`${BASE}/api${p}`, {
    method: opt.method ?? (opt.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opt.body ? JSON.stringify(opt.body) : undefined,
  });
  const t = await r.text();
  let j; try { j = JSON.parse(t); } catch { j = t; }
  if (!r.ok) throw new Error(`${p} ${r.status} ${t.slice(0, 200)}`);
  return j;
}
const login = async (persona, scenario) => jreq("/jury/login", null, { body: { persona, scenario } });
function findRef(o) {  // первый ref кандидата в ответе подборки
  if (!o || typeof o !== "object") return null;
  if (typeof o.ref === "string" && /^[A-Z]/.test(o.ref)) return o.ref;
  for (const v of Object.values(o)) { const r = findRef(v); if (r) return r; }
  return null;
}

async function prepare() {
  const e = await login("employer", "new");
  const sid = e.scenario;
  const tokens = { employer: e.access_token };
  for (const p of ["candidate", "candidate_new", "expert"]) tokens[p] = (await login(p, sid)).access_token;
  const needs = await jreq("/employer/needs", tokens.employer);
  const need = needs.find((n) => /Python|платеж/i.test(n.title)) ?? needs[0];
  const detail = await jreq(`/employer/needs/${need.id}`, tokens.employer);
  const ver = detail.selections?.[0]?.version ?? detail.versions?.[0]?.version ?? 1;
  const sel = await jreq(`/employer/needs/${need.id}/selections/${ver}`, tokens.employer).catch(() => null);
  const ref = findRef(sel) ?? "C-0001";
  return { sid, tokens, needId: need.id, ref };
}

// Экраны: persona = чей токен (null — без входа), path или go(page) — как открыть, ready — что дождаться.
function screens(ctx) {
  return [
    { id: "landing", persona: null, path: "/" },
    { id: "login", persona: null, path: "/login" },
    { id: "register", persona: null, path: "/register" },
    { id: "validation", persona: null, path: "/validation" },
    { id: "cand_overview", persona: "candidate", path: "/candidate" },
    { id: "cand_category", persona: "candidate", path: "/candidate/category" },
    { id: "cand_invitations", persona: "candidate", path: "/candidate/invitations" },
    { id: "cand_invitation_modal", persona: "candidate", path: "/candidate/invitations",
      go: async (page) => { const b = page.locator("main ul li > button").first(); if (await b.count()) { await b.focus(); await page.keyboard.press("Enter"); await page.waitForSelector('[role="dialog"]', { timeout: 8000 }); } } },
    { id: "cand_profile", persona: "candidate", path: "/candidate/profile" },
    { id: "cand_feedback", persona: "candidate", path: "/candidate/feedback" },
    { id: "test_start", persona: "candidate_new", path: "/candidate/express" },
    { id: "test_item", persona: "candidate_new", path: "/candidate/express", go: startTest },
    { id: "test_result", persona: "candidate_new", path: null, go: finishTest, after: "test_item" },
    { id: "emp_overview", persona: "employer", path: "/employer" },
    { id: "emp_needs", persona: "employer", path: "/employer/needs" },
    { id: "selection", persona: "employer", path: `/employer/needs/${ctx.needId}` },
    { id: "candidate_card", persona: "employer", path: `/employer/candidates/${ctx.ref}?need=${ctx.needId}` },
    { id: "invite_modal", persona: "employer", path: `/employer/candidates/${ctx.ref}?need=${ctx.needId}`,
      // клавиатурой: панель проводника жюри на 1440 × 900 перекрывает кнопку для мыши
      go: async (page) => { const b = page.getByRole("button", { name: "Пригласить", exact: true }); await b.focus(); await page.keyboard.press("Enter"); await page.waitForSelector('[role="dialog"]', { timeout: 8000 }); } },
    { id: "emp_invitations", persona: "employer", path: "/employer/invitations" },
    { id: "emp_probes", persona: "employer", path: "/employer/probes" },
    { id: "emp_search", persona: "employer", path: "/employer/search" },
    { id: "emp_compare", persona: "employer", path: `/employer/needs/${ctx.needId}/compare` },
    { id: "expert_home", persona: "expert", path: "/expert" },
    { id: "expert_pairs", persona: "expert", path: "/expert/pairs" },
    { id: "expert_answers", persona: "expert", path: "/expert/answers" },
    { id: "expert_angoff", persona: "expert", path: "/expert/angoff" },
    { id: "expert_review", persona: "expert", path: "/expert/review" },
  ].filter((s) => !ONLY.length || ONLY.includes(s.id));
}

async function startTest(page) {
  const consent = page.getByRole("checkbox", { name: /даю согласие оператору платформы/ });
  if (await consent.count()) await consent.check().catch(() => null);
  const start = page.getByRole("button", { name: /^Начать (экспресс-)?тест/ });
  await start.first().click({ timeout: 15000 });
  const skip = page.getByRole("button", { name: "Пройти без камеры" });
  await skip.or(page.getByText(/Задание \d+/).first()).first().waitFor({ timeout: 60000 });
  if (await skip.isVisible().catch(() => false)) await skip.click();
  await page.getByText(/Задание \d+/).first().waitFor({ timeout: 60000 });
}

async function finishTest(page) {
  const main = page.getByRole("main");
  const result = page.getByRole("heading", { level: 1, name: /^(Грейд|Принят уровень|Предварительный|Дотестирование)/ });
  for (let i = 0; i < 25; i++) {
    if (await result.isVisible().catch(() => false)) break;
    const radios = main.getByRole("radio"); const lines = main.getByRole("listbox", { name: /Строки кода/ }).getByRole("option");
    const text = main.locator("textarea#ans");
    if (await radios.count()) await radios.first().check();
    else if (await lines.count()) await lines.nth(Math.min(2, (await lines.count()) - 1)).click();
    else if (await text.count()) await text.fill("0");
    const btn = main.getByRole("button", { name: /^Ответить/ });
    if (!(await btn.count())) { const show = main.getByRole("button", { name: "Показать результат" }); if (await show.count()) await show.click(); await sleep(1500); continue; }
    const head = await main.getByText(/Задание \d+/).first().textContent().catch(() => "");
    await btn.click();
    for (let k = 0; k < 60; k++) {
      await sleep(500);
      if (await result.isVisible().catch(() => false)) break;
      const now = await main.getByText(/Задание \d+/).first().textContent({ timeout: 500 }).catch(() => null);
      if (now && now !== head) break;
    }
  }
  await result.waitFor({ timeout: 60000 });
}

async function runAxe(page) {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async () => {
    const r = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] },
      resultTypes: ["violations"],
    });
    return r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
      targets: v.nodes.slice(0, 4).map((n) => ({ target: n.target.join(" "), summary: (n.failureSummary || "").slice(0, 300), html: n.html.slice(0, 200) })) }));
  });
}

(async () => {
  const ctx = await prepare();
  let browser = await chromium.launch();
  const results = [];
  for (const [w, h] of VIEWPORTS) {
    // своя песочница на каждую ширину: тест проходит один раз в каждой
    const vctx = w === VIEWPORTS[0][0] ? ctx : await prepare();
    const contexts = {};
    async function pageFor(persona) {
      if (contexts[persona ?? "anon"]) return contexts[persona ?? "anon"];
      const c = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, locale: "ru-RU", reducedMotion: "reduce" });
      const token = persona ? vctx.tokens[persona] : null;
      await c.addInitScript(([t, sid]) => {
        if (sessionStorage.getItem("__a11y_init")) return;
        sessionStorage.setItem("__a11y_init", "1");
        if (t) { localStorage.setItem("fsp_token", t); localStorage.setItem("jury_guide", "1"); }
        if (sid) localStorage.setItem("jury_scenario", sid);
      }, [token, vctx.sid]);
      const p = await c.newPage();
      p.on("pageerror", (e) => (p.__errors ??= []).push(String(e)));
      contexts[persona ?? "anon"] = p;
      return p;
    }
    for (const s of screens(vctx)) {
     for (let attempt = 0; attempt < 2; attempt++) {
      const page = await pageFor(s.persona);
      const t0 = Date.now();
      try {
        if (s.path) { await page.goto(BASE + s.path, { waitUntil: "networkidle", timeout: 60000 }); }
        if (s.go) await s.go(page);
        await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => null);
        await sleep(600);
        const v = await runAxe(page);
        const counts = Object.fromEntries(IMPACTS.map((i) => [i, v.filter((x) => x.impact === i).length]));
        const hscroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        results.push({ screen: s.id, viewport: `${w}`, url: page.url().replace(BASE, ""), counts, total: v.length, nodes: v.reduce((a, x) => a + x.nodes, 0), hscroll, violations: v, ms: Date.now() - t0 });
        console.log(`${w} ${s.id}: ${IMPACTS.map((i) => `${i[0]}${counts[i]}`).join(" ")} hscroll=${hscroll} (${Date.now() - t0} мс)`);
        if (SHOTS) await page.screenshot({ path: path.join(OUT, "shots", `${s.id}_${w}.png`), fullPage: false });
        break;
      } catch (e) {
        // браузер закрылся (нехватка памяти на общей машине) — перезапуск и повтор экрана один раз
        if (attempt === 0 && /has been closed|crashed/.test(String(e))) {
          console.log(`${w} ${s.id}: браузер закрылся, перезапуск`);
          await browser.close().catch(() => null); browser = await chromium.launch();
          for (const k of Object.keys(contexts)) delete contexts[k];
          continue;
        }
        if (SHOTS) await page.screenshot({ path: path.join(OUT, "shots", `${s.id}_${w}_error.png`) }).catch(() => null);
        results.push({ screen: s.id, viewport: `${w}`, error: String(e).slice(0, 300) });
        console.log(`${w} ${s.id}: ОШИБКА ${String(e).slice(0, 200)}`);
        break;
      }
     }
    }
    for (const p of Object.values(contexts)) await p.context().close().catch(() => null);
  }
  await browser.close();
  // APPEND=1: дописать к прежнему OUT/axe.json (проход частями — замок браузера не дольше 5 минут за раз)
  const prevFile = path.join(OUT, "axe.json");
  if (process.env.APPEND && fs.existsSync(prevFile)) {
    const fresh = new Set(results.map((r) => `${r.screen}@${r.viewport}`));
    const old = JSON.parse(fs.readFileSync(prevFile, "utf8")).results.filter((r) => !fresh.has(`${r.screen}@${r.viewport}`));
    results.unshift(...old);
  }
  fs.writeFileSync(prevFile, JSON.stringify({ base: BASE, at: new Date().toISOString(), results }, null, 2));
  // сводка: по степеням (правило × экран × ширина) и по правилам
  const tot = Object.fromEntries(IMPACTS.map((i) => [i, 0]));
  const byRule = {};
  for (const r of results) for (const v of r.violations ?? []) {
    tot[v.impact]++;
    const k = `${v.impact} · ${v.id}`;
    (byRule[k] ??= { screens: new Set(), nodes: 0, help: v.help });
    byRule[k].screens.add(`${r.screen}@${r.viewport}`); byRule[k].nodes += v.nodes;
  }
  const lines = [`# axe-core ${BASE} — ${new Date().toISOString()}`, "",
    `Экранов × ширин: ${results.length}; ошибок открытия: ${results.filter((r) => r.error).length}.`, "",
    "| Степень | Нарушений (правило × экран × ширина) |", "|---|---|",
    ...IMPACTS.map((i) => `| ${i} | ${tot[i]} |`), "", "| Правило | Экранов | Узлов | Описание |", "|---|---|---|---|",
    ...Object.entries(byRule).sort((a, b) => IMPACTS.indexOf(a[0].split(" · ")[0]) - IMPACTS.indexOf(b[0].split(" · ")[0]) || b[1].screens.size - a[1].screens.size)
      .map(([k, v]) => `| ${k} | ${v.screens.size} | ${v.nodes} | ${v.help} |`), "",
    "| Экран | Ширина | critical | serious | moderate | minor | Гор. прокрутка, px |", "|---|---|---|---|---|---|---|",
    ...results.map((r) => r.error ? `| ${r.screen} | ${r.viewport} | ошибка: ${r.error.slice(0, 80)} | | | | |` : `| ${r.screen} | ${r.viewport} | ${IMPACTS.map((i) => r.counts[i]).join(" | ")} | ${r.hscroll} |`)];
  fs.writeFileSync(path.join(OUT, "axe_summary.md"), lines.join("\n") + "\n");
  console.log(`итого: ${IMPACTS.map((i) => `${i} ${tot[i]}`).join(", ")} → ${OUT}/axe_summary.md`);
})().catch((e) => { console.error(e); process.exit(1); });
