/**
 * Я15 «Устная защита ответа и ИИ-интервью» — только когда на стенде включён INTERVIEW_ENABLED (по умолчанию выкл.,
 * тогда тест пропускается). Проверяется на заглушке движка (INTERVIEW_ENGINE=stub или движок без ключа модели):
 * вопросы по шаблону, оценка — правилом, кнопка «Подставить начало письменного ответа (заглушка)» отвечает за кандидата.
 *  1. Кандидат с развёрнутыми ответами (Мария): категория → «Подтвердите авторство ответа» с готовым примером песочницы
 *     («пример, модельный кандидат») → согласие → разговор в чате (канал «текст») → итог «ответ подтверждён устно».
 *     Визуал собеседника — своя анимация (VoiceWave, состояния «говорю / слушаю / думаю»), видео и лиц нет (п. 5.11).
 *     Если на стенде есть «нажми и говори» (INTERVIEW_STT_STUB=true на заглушке), первый ответ записывается с фальшивого
 *     микрофона Chromium и распознаётся заглушкой — проверяется общий компонент записи голоса.
 *  2. Работодатель: значок на карточке кандидата и подробности с подтверждёнными цитатами и расшифровкой.
 *  3. Этап найма «ИИ-интервью»: работодатель приглашает в принятом приглашении, кандидат (390 px) проходит его до конца;
 *     итог кандидату не показывается, работодатель видит его в приглашении.
 *  4. 390 px: панель защиты, разговор и карточка работодателя без горизонтальной прокрутки, снимки.
 * В1: при INTERVIEW_AVATAR_ENABLED (/api/meta interview.avatar) вместо волны — свой образ (сгенерированный портрет) «ИИ-интервьюер, не
 * человек» (interviewer-avatar): в 1440 px играет беззвучный клип текущего состояния (data-mode=video); в 390 px —
 * до начала разговора с prefers-reduced-motion неподвижный кадр без <video>, затем клипы недоступны (запросы обрываются) —
 * запасной вариант: неподвижный кадр и свечение рамки по голосу (data-mode=still). Флаг выключен — проверяется прежний визуал.
 * axe-core (E2E_AXE=<путь к axe.min.js>, например tools/a11y/axe_audit.cjs → /tmp/axe.min.js): нарушений уровня
 * serious/critical на новых экранах нет. Без E2E_AXE проверка доступности пропускается (пакеты не добавляются).
 */
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, newPersonaContext, test } from "../lib/fixtures";
import { apiContext, apiGet, juryToken } from "../lib/stand";
import { juryEnter } from "../lib/ui";

test.describe.configure({ mode: "serial" });
// фальшивый микрофон Chromium (тон 440 Гц) и автоматическое разрешение — для «нажми и говори» на заглушке
test.use({ launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] }, permissions: ["microphone"] });

const SHOTS = process.env.E2E_SHOTS_DIR || resolve(process.cwd(), "reports/mobile");
const AXE = process.env.E2E_AXE;
let enabled = false;
let avatar = false;  // В1: INTERVIEW_AVATAR_ENABLED — свой образ интервьюера вместо волны
let mariaRef = "";
const VIS = () => (avatar ? "interviewer-avatar" : "voice-wave");

async function noHScroll(page: Page, what: string) {
  const w = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(w, `${what}: горизонтальная прокрутка`).toBeLessThanOrEqual(1);
}

/** Свой визуал собеседника: волна голоса (флаг образа выкл.) или свой образ — сгенерированный портрет (вкл.) и подпись состояния. */
async function visualOk(page: Page, opts: { still?: boolean } = {}) {
  const w = page.getByTestId(VIS());
  await expect(w).toBeVisible();
  await expect(w).toHaveAttribute("data-state", /^(speaking|listening|thinking)$/);
  await expect(w).toContainText("Интервьюер:");
  await expect(w).toContainText("модель, не люди");
  if (!avatar) {
    await expect(page.locator("video")).toHaveCount(0);
  } else {
    await expect(w).toContainText("ИИ-интервьюер, не человек");
    await expect(w.getByTestId("avatar-still")).toHaveAttribute("alt", /несуществующий человек/);
    if (opts.still) {  // клипов нет (не загрузились) — запасной вариант: неподвижный кадр и свечение рамки, клипы не видны
      await expect(w).toHaveAttribute("data-mode", "still");
      await expect(w.getByTestId("avatar-still")).toBeVisible();
    } else {  // клип текущего состояния играет, все клипы без звука и скрыты от чтения с экрана
      await expect(w).toHaveAttribute("data-mode", "video", { timeout: 20_000 });
      const clips = await w.locator("video").evaluateAll((vs) => vs.map((v) => {
        const el = v as HTMLVideoElement & { webkitAudioDecodedByteCount?: number };
        return { muted: el.muted, hidden: el.getAttribute("aria-hidden"), playing: !el.paused,
                 audio: el.webkitAudioDecodedByteCount ?? 0, id: el.dataset.testid ?? "" };
      }));
      expect(clips.length).toBeGreaterThan(0);
      expect(clips.every((c) => c.muted && c.hidden === "true" && c.audio === 0)).toBe(true);
      expect(clips.some((c) => c.playing)).toBe(true);
    }
  }
  await expect(w).toHaveAttribute("data-state", "listening", { timeout: 15_000 });  // прочитал вопрос → ждёт ответа
}

/** Ответить на вопросы до конца разговора: подсказка заглушки или свой текст; первый ответ — голосом, если можно. */
async function talk(page: Page, done: ReturnType<Page["getByTestId"]>, opts: { voiceFirst?: boolean; axeWhat?: string; shot?: string; still?: boolean } = {}) {
  const q = page.getByTestId("iv-question");
  // вопрос может смениться или исчезнуть (конец разговора) между проверками — короткое ожидание, без 20 с по умолчанию
  const cur = async () => (await q.first().textContent({ timeout: 1_000 }).catch(() => "")) ?? "";
  let prev = "";
  for (let i = 0; i < 8; i++) {
    // следующий вопрос (не прежний) или конец разговора
    await expect.poll(async () => (await done.isVisible()) || !["", prev].includes(await cur()), { timeout: 90_000 }).toBe(true);
    if (await done.isVisible()) return;
    prev = await cur();
    if (i === 0) {
      await visualOk(page, { still: opts.still });
      if (opts.axeWhat) await axe(page, opts.axeWhat, avatar);
      if (opts.shot) { mkdirSync(SHOTS, { recursive: true }); await page.screenshot({ path: resolve(SHOTS, opts.shot), fullPage: true }); }
    }
    const field = page.getByLabel("Ваш ответ");
    const rec = page.getByTestId("iv-record");
    if (i === 0 && opts.voiceFirst && await rec.isVisible()) {
      await rec.click();
      await expect(rec).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });
      await expect(page.getByTestId(VIS())).toHaveAttribute("data-state", "listening");
      await page.waitForTimeout(1500);
      await rec.click();
      await expect(field).not.toHaveValue("", { timeout: 30_000 });  // распознанный текст — в поле, на проверку
      await expect(page.getByRole("status").filter({ hasText: /Проверьте распознанный текст|Распознавание — заглушка/ })).toBeVisible();
    } else {
      const hint = page.getByTestId("iv-hint");
      if (await hint.isVisible()) await hint.click();
      else await field.fill("Отвечаю своими словами: сначала проверяю входные данные, затем выбираю структуру и объясняю почему, на примере из своей работы с очередями и код-ревью.");
    }
    await page.getByTestId("iv-send").click();
  }
  await expect(done).toBeVisible({ timeout: 90_000 });
}

/** axe: нарушения serious/critical; strict — любые (В1: экран разговора со своим образом — 0 нарушений любого уровня). */
async function axe(page: Page, what: string, strict = false) {
  if (!AXE) return;
  await page.addScriptTag({ path: AXE });
  const bad = await page.evaluate(async (all) => {
    // @ts-expect-error axe подключён в страницу
    const r = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
    return r.violations.filter((v: any) => all || v.impact === "serious" || v.impact === "critical")
      .map((v: any) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 2).map((n: any) => n.target.join(" ")).join(" | ")}`);
  }, strict);
  expect(bad, `${what}: axe ${strict ? "все уровни" : "serious/critical"}`).toEqual([]);
}

test.beforeAll(async () => {
  const api = await apiContext();
  try {
    const meta = await (await api.get("/api/meta")).json();
    enabled = meta.interview_enabled === true;
    avatar = enabled && meta.interview?.avatar === true;
    if (enabled) mariaRef = (await apiGet(api, "/me", await juryToken(api, "candidate"))).candidate.public_ref;
  } finally {
    await api.dispose();
  }
});

test("кандидат: устная защита в чате на заглушке → «ответ подтверждён устно»; работодатель видит значок и цитаты", async ({ page, browser }) => {
  test.skip(!enabled, "INTERVIEW_ENABLED выключен на стенде");
  await page.setViewportSize({ width: 1440, height: 900 });
  await juryEnter(page, "candidate");
  await test.step("категория: панель «Подтвердите авторство ответа» и готовый пример песочницы", async () => {
    await page.goto("/candidate/category#defense", { waitUntil: "domcontentloaded" });
    const panel = page.getByTestId("defense-panel");
    await expect(panel).toBeVisible({ timeout: 60_000 });
    await expect(panel.getByRole("heading", { name: /^Подтвердите авторство ответа: устная защита \d+ минут/ })).toBeVisible();
    await expect(panel).toContainText("Грейд не меняется");
    await expect(panel.getByTestId("defense-example")).toContainText("пример, модельный кандидат");
    await axe(page, "категория с панелью защиты");
  });
  await test.step("согласие → разговор в чате", async () => {
    const panel = page.getByTestId("defense-panel");
    await panel.getByTestId("defense-open").click();
    await panel.getByRole("checkbox").check();
    await panel.getByTestId("interview-defense-start").click();
    await expect(page).toHaveURL(/\/candidate\/interview\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    await expect(page.getByTestId(VIS())).toHaveAttribute("data-state", "idle");
    await page.getByTestId("iv-begin-text").click();
    const result = page.getByTestId("interview-result");
    await talk(page, result, { voiceFirst: true, axeWhat: "разговор", shot: avatar ? "14-interview-room-avatar-1440.png" : "14-interview-room-1440.png" });
    await expect(result).toBeVisible({ timeout: 90_000 });
    await expect(result).toContainText(/Ответ подтверждён устно|Есть расхождения|Мало данных/);
    await expect(result).toContainText("заглушка");
    await axe(page, "итог разговора");
  });
  await test.step("работодатель: значок в карточке и подробности с цитатами", async () => {
    const emp = await (await newPersonaContext(browser)).newPage();
    await emp.setViewportSize({ width: 1440, height: 900 });
    await juryEnter(emp, "employer");
    await emp.goto(`/employer/candidates/${mariaRef}`, { waitUntil: "domcontentloaded" });
    await expect(emp.getByTestId("defense-badge").first()).toBeVisible({ timeout: 60_000 });
    const d = emp.getByTestId("defense-details");
    await expect(d).toBeVisible();
    await expect(d.getByTestId("interview-result")).toBeVisible();
    await expect(d).toContainText("модель, не люди");
    await axe(emp, "карточка кандидата у работодателя");
    await emp.context().close();
  });
});

test("этап найма «ИИ-интервью»: приглашение работодателя → кандидат проходит (390 px) → итог у работодателя", async ({ page, browser }) => {
  test.skip(!enabled, "INTERVIEW_ENABLED выключен на стенде");
  const api = await apiContext();
  let invId = "";
  try {
    const te = await juryToken(api, "employer");
    const tc = await juryToken(api, "candidate");
    const r = await api.post("/api/employer/invitations", {
      headers: { Authorization: `Bearer ${te}` },
      data: { position_title: "Python-разработчик (ИИ-интервью)", offer_description: "Платёжный API, команда 6 человек.",
              salary_from: 220000, salary_to: 300000, contact_method: "Telegram @hr_demo", candidate_ref: mariaRef },
    });
    test.skip(!r.ok(), `приглашение не создано (${r.status()}) — правило повторных приглашений песочницы`);
    invId = (await r.json()).id;
    expect((await api.post(`/api/candidate/invitations/${invId}/accept`, { headers: { Authorization: `Bearer ${tc}` } })).ok()).toBe(true);
  } finally {
    await api.dispose();
  }
  await juryEnter(page, "employer");
  await page.goto("/employer/invitations", { waitUntil: "domcontentloaded" });
  const block = page.getByTestId("ai-interview-employer").filter({ has: page.getByRole("button", { name: "Пригласить на ИИ-интервью" }) }).first();
  await expect(block).toBeVisible({ timeout: 60_000 });
  const skills = block.getByLabel("Добавить навыки (через запятую)");
  if (await skills.inputValue() === "") await skills.fill("Kafka, код-ревью");
  await block.getByRole("button", { name: "Пригласить на ИИ-интервью" }).click();
  await expect(page.getByTestId("ai-interview-employer").filter({ hasText: "Приглашение отправлено" }).first()).toBeVisible();
  await axe(page, "приглашения работодателя");

  const cand = await (await newPersonaContext(browser)).newPage();
  if (avatar) {  // В1: сначала «уменьшить движение», затем клипы недоступны — запасной вариант
    await cand.emulateMedia({ reducedMotion: "reduce" });
    await cand.route(/\/avatar\/[a-z]+\.(webm|mp4)$/, (r) => r.abort());
  }
  await juryEnter(cand, "candidate");
  await cand.goto("/candidate/invitations", { waitUntil: "domcontentloaded" });
  await cand.getByText("Python-разработчик (ИИ-интервью)").first().click();
  const ai = cand.getByTestId("ai-interview-candidate");
  await expect(ai).toBeVisible({ timeout: 60_000 });
  await expect(ai).toContainText("Компания приглашает на ИИ-интервью");
  await expect(ai.getByRole("button", { name: "Начать ИИ-интервью" })).toBeVisible();
  await axe(cand, "приглашение кандидата");
  await cand.setViewportSize({ width: 390, height: 844 });
  await ai.getByRole("checkbox").check();
  await ai.getByRole("button", { name: "Начать ИИ-интервью" }).click();
  // песочница жюри: живой запуск — 1 в час (INTERVIEW_JURY_PER_HOUR); защита в тесте 1 его уже использовала
  const limit = ai.getByRole("alert").filter({ hasText: "один живой запуск в час" });
  await expect.poll(async () => /\/candidate\/interview\/[0-9a-f-]{36}$/.test(cand.url()) || (await limit.isVisible()), { timeout: 60_000 }).toBe(true);
  if (await limit.isVisible()) {
    test.info().annotations.push({ type: "limit", description: "лимит жюри 1 в час — разговор ИИ-интервью не проверен (локально: INTERVIEW_JURY_PER_HOUR=3)" });
    await cand.context().close();
    return;
  }
  if (avatar) {
    const av = cand.getByTestId("interviewer-avatar");
    await expect(av).toHaveAttribute("data-mode", "still");  // prefers-reduced-motion: неподвижный кадр
    await expect(cand.locator("video")).toHaveCount(0);
    await cand.emulateMedia({ reducedMotion: "no-preference" });  // движение разрешено, но клипы не грузятся
    await expect.poll(async () => cand.locator("video").count(), { timeout: 15_000 }).toBeGreaterThan(0);
    await expect(av).toHaveAttribute("data-mode", "still");
  }
  await cand.getByTestId("iv-begin-text").click();
  await expect(cand.getByTestId("iv-question")).toBeVisible({ timeout: 60_000 });
  await noHScroll(cand, "разговор ИИ-интервью, 390 px");
  mkdirSync(SHOTS, { recursive: true });
  await cand.screenshot({ path: resolve(SHOTS, avatar ? "14-interview-room-avatar-390.png" : "14-interview-room-390.png"), fullPage: true });
  const done = cand.getByTestId("iv-done");
  await talk(cand, done, { axeWhat: "разговор ИИ-интервью, 390 px", still: avatar });
  await expect(done).toContainText("видит только пригласившая компания");
  await cand.context().close();

  await page.reload({ waitUntil: "domcontentloaded" });
  const res = page.getByTestId("ai-interview-employer").getByTestId("interview-result").first();
  await expect(res).toBeVisible({ timeout: 60_000 });
  await expect(res).toContainText("модель, не люди");
});

test("390 px: панель защиты, разговор и карточка работодателя без горизонтальной прокрутки", async ({ page, browser }) => {
  test.skip(!enabled, "INTERVIEW_ENABLED выключен на стенде");
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await juryEnter(page, "candidate");
  await page.goto("/candidate/category#defense", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("defense-panel")).toBeVisible({ timeout: 60_000 });
  await noHScroll(page, "категория, панель защиты");
  await page.getByTestId("defense-panel").screenshot({ path: resolve(SHOTS, "14-interview-panel-390.png") });
  const emp = await (await newPersonaContext(browser)).newPage();
  await emp.setViewportSize({ width: 390, height: 844 });
  await juryEnter(emp, "employer");
  await emp.goto(`/employer/candidates/${mariaRef}`, { waitUntil: "domcontentloaded" });
  await expect(emp.getByTestId("defense-details")).toBeVisible({ timeout: 60_000 });
  await noHScroll(emp, "карточка кандидата, устная защита");
  await emp.getByTestId("defense-details").screenshot({ path: resolve(SHOTS, "14-interview-employer-390.png") });
  await emp.context().close();
});
