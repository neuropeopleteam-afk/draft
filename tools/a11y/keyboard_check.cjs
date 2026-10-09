// Путь жюри без мыши (1440 × 900): только Tab / Shift+Tab / Enter / пробел / стрелки / Esc.
//   BASE=http://127.0.0.1:5138 OUT=/tmp/a11y/kbd node tools/a11y/keyboard_check.cjs
// Проверяется: первая остановка Tab — «Перейти к содержимому» и она ведёт в <main>; у каждой остановки виден фокус
// (outline или box-shadow); вход жюри, потребность → подборка → карточка → «Пригласить» → окно держит фокус,
// закрывается Esc, фокус возвращается на кнопку; экспресс-тест: согласие, старт, без камеры, ответы с клавиатуры,
// после ответа фокус на новом задании. Итог — OUT/keyboard.json и строки в консоли.
const path = require("path");
const fs = require("fs");
const ROOT = path.resolve(__dirname, "../..");
const { chromium } = require(path.join(ROOT, "e2e/node_modules/playwright-core"));
const BASE = process.env.BASE || "http://127.0.0.1:5138";
const OUT = process.env.OUT || "/tmp/a11y/kbd";
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(`${pass ? "ДА " : "НЕТ"} ${name}${detail ? " — " + detail : ""}`); };

/** Описание элемента в фокусе и видимость индикатора фокуса. */
const focusInfo = (page) => page.evaluate(() => {
  const a = document.activeElement;
  if (!a || a === document.body) return { tag: "body", text: "", visible: false };
  const cs = getComputedStyle(a);
  const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow && cs.boxShadow !== "none";
  // кастомные переключатели: фокус на скрытом input, кольцо рисует соседний элемент (peer-focus-visible)
  const sib = a.nextElementSibling ? getComputedStyle(a.nextElementSibling).boxShadow : "none";
  const r = a.getBoundingClientRect();
  return {
    tag: a.tagName.toLowerCase(), role: a.getAttribute("role"), text: (a.getAttribute("aria-label") || a.textContent || a.getAttribute("value") || "").trim().replace(/\s+/g, " ").slice(0, 70),
    href: a.getAttribute("href"), inDialog: !!a.closest('[role="dialog"]'), inMain: !!a.closest("main"),
    visible: outline || !!shadow || (sib && sib !== "none"), onScreen: r.bottom > 0 && r.top < innerHeight && r.width > 0,
  };
});

/** Tab до элемента, для которого pred(info) истинно. Возвращает число нажатий (или -1) и все остановки. */
async function tabTo(page, pred, max = 160) {
  const stops = [];
  for (let i = 1; i <= max; i++) {
    await page.keyboard.press("Tab");
    const f = await focusInfo(page);
    stops.push(f);
    if (pred(f)) return { n: i, stops };
  }
  console.log("   не найдено; последние остановки: " + stops.slice(-8).map((s) => `${s.tag}«${s.text.slice(0, 30)}»`).join(", ") + ` · ${page.url()}`);
  return { n: -1, stops };
}
const noFocusRing = (stops) => stops.filter((s) => s.tag !== "body" && !s.visible);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ru-RU", reducedMotion: "reduce" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const invisible = {};

  // 1. Главная: пропуск навигации
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  const first = await focusInfo(page);
  ok("главная: первая остановка Tab — «Перейти к содержимому»", /Перейти к содержимому/.test(first.text), `${first.tag} «${first.text}»`);
  ok("главная: ссылка пропуска видна при фокусе", first.visible && first.onScreen);
  if (/Перейти к содержимому/.test(first.text)) {
    await page.keyboard.press("Enter"); await sleep(300);
    const after = await page.evaluate(() => ({ tag: document.activeElement?.tagName.toLowerCase(), inMain: !!document.activeElement?.closest("main") }));
    ok("главная: Enter на ссылке пропуска переносит фокус в <main>", after.inMain, after.tag);
  }

  // 2. Вход жюри с клавиатуры: Tab до «Войти как: Работодатель»
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  let t = await tabTo(page, (f) => f.tag === "button" && /Войти как:?\s*Работодатель/.test(f.text));
  invisible.landing = noFocusRing(t.stops);
  ok("главная: «Войти как: Работодатель» достижима Tab", t.n > 0, `нажатий Tab: ${t.n}`);
  ok("главная: у всех остановок до входа виден фокус", invisible.landing.length === 0, invisible.landing.map((s) => `${s.tag} «${s.text}»`).join("; "));
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/employer$/, { timeout: 60000 });
  await page.waitForLoadState("networkidle");
  // проводник жюри открыт после входа; оставляем как есть (так видит жюри)

  // 3. Кабинет: первая остановка — пропуск навигации; меню → «Потребности и подборки»
  await page.keyboard.press("Tab");
  const cab = await focusInfo(page);
  ok("кабинет: первая остановка Tab после входа — «Перейти к содержимому»", /Перейти к содержимому|К содержимому/.test(cab.text), `${cab.tag} «${cab.text}»`);
  t = await tabTo(page, (f) => f.tag === "a" && f.text === "Потребности и подборки");
  ok("кабинет: пункт меню «Потребности и подборки» достижим Tab", t.n > 0, `нажатий: ${t.n}`);
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/employer\/needs$/); await page.waitForLoadState("networkidle"); await sleep(400);
  const afterNav = await focusInfo(page);
  ok("после перехода по меню фокус не потерян (не body)", afterNav.tag !== "body", `${afterNav.tag} «${afterNav.text}»`);

  // 4. Потребность → подборка
  t = await tabTo(page, (f) => f.tag === "a" && /\/employer\/needs\/[\w-]+$/.test(f.href || ""), 200);
  invisible.needs = noFocusRing(t.stops);
  ok("потребности: ссылка на подборку достижима Tab", t.n > 0, `нажатий: ${t.n}`);
  ok("потребности: у всех остановок виден фокус", invisible.needs.length === 0, invisible.needs.map((s) => `${s.tag} «${s.text}»`).slice(0, 6).join("; "));
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/employer\/needs\/[\w-]+$/);
  await page.waitForSelector('main a[href*="/employer/candidates/"]', { timeout: 90000 }); await sleep(600);
  const live = await page.evaluate(() => [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')].map((e) => `${e.getAttribute("role") || ""}/${e.getAttribute("aria-live") || ""}: ${(e.textContent || "").trim().slice(0, 60)}`));
  ok("подборка: есть живая область (role=status / aria-live) для обновления", live.length > 0, live.slice(0, 3).join(" | "));
  t = await tabTo(page, (f) => f.tag === "a" && /\/employer\/candidates\//.test(f.href || ""), 250);
  invisible.selection = noFocusRing(t.stops);
  ok("подборка: карточка кандидата достижима Tab", t.n > 0, `нажатий: ${t.n}`);
  ok("подборка: у всех остановок виден фокус", invisible.selection.length === 0, invisible.selection.map((s) => `${s.tag} «${s.text}»`).slice(0, 6).join("; "));
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/employer\/candidates\//); await page.waitForLoadState("networkidle"); await sleep(500);

  // 5. «Пригласить» → окно: фокус внутри, Tab не выходит, Esc закрывает, фокус возвращается
  t = await tabTo(page, (f) => f.tag === "button" && f.text === "Пригласить", 120);
  ok("карточка: «Пригласить» достижима Tab", t.n > 0, `нажатий: ${t.n}`);
  await page.keyboard.press("Enter");
  await page.waitForSelector('[role="dialog"]', { timeout: 8000 });
  await sleep(200);
  const inDlg = await focusInfo(page);
  ok("окно приглашения: фокус внутри окна при открытии", inDlg.inDialog, `${inDlg.tag} «${inDlg.text}»`);
  const dlgName = await page.evaluate(() => { const d = document.querySelector('[role="dialog"]'); const id = d?.getAttribute("aria-labelledby"); return (d?.getAttribute("aria-label") || (id && document.getElementById(id)?.textContent) || "").trim(); });
  ok("окно приглашения: у окна есть доступное имя", !!dlgName, dlgName);
  let left = 0; const dstops = [];
  for (let i = 0; i < 40; i++) { await page.keyboard.press("Tab"); const f = await focusInfo(page); dstops.push(f); if (!f.inDialog) left++; }
  for (let i = 0; i < 5; i++) { await page.keyboard.press("Shift+Tab"); const f = await focusInfo(page); if (!f.inDialog) left++; }
  invisible.dialog = noFocusRing(dstops);
  ok("окно приглашения: Tab и Shift+Tab не выводят фокус из окна (45 нажатий)", left === 0, `вне окна: ${left}`);
  ok("окно приглашения: у всех остановок виден фокус", invisible.dialog.length === 0, [...new Set(invisible.dialog.map((s) => `${s.tag} «${s.text}»`))].slice(0, 6).join("; "));
  await page.keyboard.press("Escape"); await sleep(300);
  const closed = await page.evaluate(() => !document.querySelector('[role="dialog"]'));
  const back = await focusInfo(page);
  ok("окно приглашения: Esc закрывает", closed);
  ok("окно приглашения: после закрытия фокус на «Пригласить»", back.text === "Пригласить", `${back.tag} «${back.text}»`);

  // 6. Экспресс-тест с клавиатуры (новый контекст: вход «Пройдите тест сами»)
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ru-RU", reducedMotion: "reduce" });
  const p2 = await ctx2.newPage();
  p2.on("pageerror", (e) => errors.push(String(e)));
  await p2.goto(BASE + "/", { waitUntil: "networkidle" });
  t = await tabTo(p2, (f) => f.tag === "button" && /Войти как:?\s*Пройдите тест сами/.test(f.text));
  ok("главная: «Войти как: Пройдите тест сами» достижима Tab", t.n > 0, `нажатий: ${t.n}`);
  await p2.keyboard.press("Enter");
  await p2.waitForURL(/\/candidate\/express$/, { timeout: 60000 }); await p2.waitForLoadState("networkidle"); await sleep(500);
  // чекбокс согласия: подпись — в окружающем <label>
  const consentStops = [];
  let consentFocused = false;
  for (let i = 0; i < 160 && !consentFocused; i++) {
    await p2.keyboard.press("Tab");
    consentStops.push(await focusInfo(p2));
    consentFocused = await p2.evaluate(() => { const a = document.activeElement; return a?.type === "checkbox" && /согласие/i.test(a.closest("label")?.textContent || ""); });
  }
  t = { stops: consentStops };
  ok("тест: чекбокс согласия достижим Tab", consentFocused);
  invisible.test_start = noFocusRing(t.stops);
  ok("тест: у остановок на экране перед тестом виден фокус", invisible.test_start.length === 0, [...new Set(invisible.test_start.map((s) => `${s.tag} «${s.text}»`))].slice(0, 6).join("; "));
  await p2.keyboard.press("Space");
  t = await tabTo(p2, (f) => f.tag === "button" && /^Начать (экспресс-)?тест/.test(f.text), 40);
  ok("тест: «Начать экспресс-тест» достижима Tab после согласия", t.n > 0, `нажатий: ${t.n}`);
  await p2.keyboard.press("Enter");
  await p2.waitForSelector("text=/Пройти без камеры|Задание \\d+/", { timeout: 60000 });
  if (await p2.getByRole("button", { name: "Пройти без камеры" }).count()) {
    t = await tabTo(p2, (f) => f.tag === "button" && f.text === "Пройти без камеры", 40);
    ok("тест: «Пройти без камеры» достижима Tab", t.n > 0, `нажатий: ${t.n}`);
    await p2.keyboard.press("Enter");
  }
  await p2.waitForSelector("text=/Задание \\d+/", { timeout: 60000 }); await sleep(400);
  const timer = await p2.evaluate(() => { const e = document.querySelector('[role="timer"]'); return e ? (e.getAttribute("aria-label") || e.textContent || "").trim() : null; });
  ok("тест: таймер задания размечен role=timer", !!timer, timer || "нет");
  const h1 = await p2.evaluate(() => document.querySelector("main h1")?.textContent?.trim() || null);
  ok("тест: у экрана задания есть заголовок h1", !!h1, h1 || "нет");
  let answered = 0, focusOnNew = 0;
  for (let k = 0; k < 4; k++) {
    if (await p2.getByRole("heading", { level: 1, name: /^(Грейд|Принят|Предварительный|Дотестирование)/ }).count()) break;
    const before = await p2.evaluate(() => document.querySelector("main")?.innerText.match(/Задание \d+[^\n]*/)?.[0] || "");
    const kind = await p2.evaluate(() => document.querySelector('main input[type="radio"]') ? "radio" : document.querySelector('main [role="option"]') ? "line" : document.querySelector("main textarea#ans") ? "text" : "?");
    if (kind === "radio") { t = await tabTo(p2, (f) => f.tag === "input", 60); await p2.keyboard.press("Space"); await p2.keyboard.press("ArrowDown"); }
    else if (kind === "line") { t = await tabTo(p2, (f) => f.role === "option", 60); await p2.keyboard.press("ArrowDown"); }
    else if (kind === "text") { t = await tabTo(p2, (f) => f.tag === "textarea", 60); await p2.keyboard.type("0"); }
    const tb = await tabTo(p2, (f) => f.tag === "button" && /^Ответить/.test(f.text), 60);
    if (tb.n < 0) { ok(`тест: задание ${k + 1} (${kind}) — «Ответить» достижима Tab`, false); break; }
    await p2.keyboard.press("Enter");
    for (let w = 0; w < 120; w++) { await sleep(500); const now = await p2.evaluate(() => document.querySelector("main")?.innerText.match(/Задание \d+[^\n]*/)?.[0] || ""); if (now !== before) break; }
    await sleep(500);
    answered++;
    const f = await focusInfo(p2);
    const fh = await p2.evaluate(() => { const a = document.activeElement; return !!a && (a.tagName === "H1" || a.tagName === "MAIN" || !!a.closest?.("main h1")); });
    if (fh) focusOnNew++;
    console.log(`   задание ${k + 1}: ${kind}, после ответа фокус: ${f.tag} «${f.text}»`);
  }
  ok("тест: ответы на задания с клавиатуры", answered > 0, `отвечено: ${answered}`);
  ok("тест: после ответа фокус переходит к новому заданию (заголовок)", answered > 0 && focusOnNew === answered, `${focusOnNew} из ${answered}`);
  const liveTest = await p2.evaluate(() => [...document.querySelectorAll('[aria-live="polite"], [role="status"]')].map((e) => (e.textContent || "").trim()).filter(Boolean).slice(0, 3));
  // объявление нового задания: фокус на заголовке «Задание N» (диктор читает его сразу) или живая область
  ok("тест: новое задание объявляется (фокус на заголовке или живая область)", (answered > 0 && focusOnNew === answered) || liveTest.some((x) => /Задание/.test(x)), `фокус на заголовке ${focusOnNew} из ${answered}; живые области: ${liveTest.join(" | ") || "—"}`);

  ok("ошибок JavaScript на страницах нет", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
  const passed = checks.filter((c) => c.pass).length;
  fs.writeFileSync(path.join(OUT, "keyboard.json"), JSON.stringify({ base: BASE, at: new Date().toISOString(), passed, total: checks.length, checks, invisible }, null, 2));
  console.log(`итого: ${passed} из ${checks.length} → ${OUT}/keyboard.json`);
})().catch((e) => { console.error(e); process.exit(1); });
