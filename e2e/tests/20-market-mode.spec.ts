/**
 * «Рыночный режим» по всем страницам (решение владельца 20.10, п. 2): настоящие учётки — аноним, кандидат,
 * работодатель, представитель ФСП (не жюри, is_demo = false) — не видят демо: ни панели «Роль в 1 клик», ни
 * проводника жюри «Ваш маршрут», ни кнопок сброса песочницы, ни подписей «Демо жюри», «демо-профиль», «для жюри»,
 * ни демо-компаний и демо-кандидатов. Единственный вход в демо — вкладка «Демо для жюри» (/demo) и ссылки жюри.
 *
 * Маршруты — из frontend/src/App.tsx (разбор вложенных <Route>), а не список вручную: каждая страница каждой роли.
 * Пропускаются только демо-пространства (/demo*, /jury*, /x/, /j/), чужие роли (админ, эксперт) и адреса
 * с параметрами без объекта. Настоящие кандидат и работодатель регистрируются через API стенда (DEV_MODE: код
 * подтверждения приходит в ответе); представитель ФСП — токен из E2E_FSP_TOKEN (регистрация этой роли через API
 * закрыта; на пробном стенде токен выдаёт tools/ci/fsp_token.sh или `docker exec … issue_token`).
 * E2E_DEMO_MARKERS — путь к JSON со списком названий демо-компаний и номеров демо-профилей (необязательно).
 *
 * Итог — все находки разом: страница, роль, что найдено (reports/market_mode.json).
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { apiContext, BASE_URL } from "../lib/stand";

const APP_TSX = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../frontend/src/App.tsx");
const FORBIDDEN_TEXT = [
  "Роль в 1 клик", "Ваш маршрут", "Быстрый переход для жюри", "Демо-аккаунт для жюри", "Сбросить песочницу",
  "Сбросить демо", "Демо жюри", "демо-профиль", "Демо-профиль", "Демо-кандидат", "демо-кандидат", "для жюри",
];
const FORBIDDEN_TESTIDS = ["cabinet-top-bar", "cabinet-route", "jury-panel", "jury-guide", "jury-quick", "jury-reset"];
const SKIP = [/^\/demo/, /^\/jury/, /^\/x\//, /^\/j\//, /^\/admin/, /^\/expert/, /^\/share\//, /^\/expert-invite\//,
  /^\/verify\//, /^\/fsp-id\//, /^\/login\/2fa/, /^\/reset/, /^\/sus/, /^\/tariffs\/live/, /:/, /\*/];

type Role = "anon" | "candidate" | "employer" | "fsp";

/** Полные пути всех <Route path=…> из App.tsx с учётом вложенности. Тег разбирается с учётом {…}: внутри
 * element={<Navigate … />} есть свои «>», по ним тег не заканчивается. */
export function appRoutes(src = fs.readFileSync(APP_TSX, "utf8")): string[] {
  const out = new Set<string>();
  const stack: string[] = [];
  let i = 0;
  while (i < src.length) {
    const open = src.indexOf("<Route", i);
    const close = src.indexOf("</Route>", i);
    if (open < 0 && close < 0) break;
    if (close >= 0 && (open < 0 || close < open)) { stack.pop(); i = close + 8; continue; }
    if (!/[\s>]/.test(src[open + 6] || "")) { i = open + 6; continue; } // <RouteBoundary> и т.п.
    let j = open + 6, depth = 0;
    for (; j < src.length; j++) {
      const c = src[j];
      if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0) break;
    }
    const attrs = src.slice(open + 6, j);
    const selfClose = attrs.trimEnd().endsWith("/");
    const top = attrs.replace(/\{[^{}]*(\{[^{}]*\}[^{}]*)*\}/g, "{}"); // атрибуты верхнего уровня
    const p = /\bpath="([^"]*)"/.exec(top)?.[1];
    const index = /\bindex\b/.test(top);
    const parent = stack.length ? stack[stack.length - 1] : "";
    const full = p === undefined ? parent : p.startsWith("/") ? p : `${parent.replace(/\/$/, "")}/${p}`;
    if (p !== undefined || index) out.add(full || "/");
    if (!selfClose) stack.push(full);
    i = j + 1;
  }
  return [...out].sort();
}

function rolePages(all: string[], role: Role): string[] {
  const own = (p: string) =>
    role === "candidate" ? p.startsWith("/candidate") : role === "employer" ? p.startsWith("/employer")
      : role === "fsp" ? p.startsWith("/fsp") : false;
  const cabinet = (p: string) => /^\/(candidate|employer|fsp)(\/|$)/.test(p);
  return all.filter((p) => !SKIP.some((r) => r.test(p)) && (cabinet(p) ? own(p) : true));
}

async function realToken(role: "candidate" | "employer"): Promise<string> {
  const api = await apiContext();
  const email = `market-${role}-${Date.now()}@example.org`;
  const r = await api.post("/api/auth/register", { data: {
    email, password: "Market-pass-123", role, consent_processing: true,
    ...(role === "employer" ? { company_name: "ООО «Рыночный режим»" } : {}),
  } });
  expect(r.status(), await r.text()).toBe(201);
  const code = (await r.json()).dev_verification_code;
  expect(code, "стенд без DEV_MODE: код подтверждения не вернулся").toBeTruthy();
  const v = await api.post("/api/auth/verify-email", { data: { email, code } });
  expect(v.status(), await v.text()).toBe(200);
  return (await v.json()).access_token;
}

function demoMarkers(): string[] {
  const f = process.env.E2E_DEMO_MARKERS;
  if (!f || !fs.existsSync(f)) return [];
  const d = JSON.parse(fs.readFileSync(f, "utf8"));
  return [...(d.companies || []), ...(d.refs || [])].filter((s: string) => s && s.length >= 6);
}

async function scanPage(page: Page, url: string, markers: string[]): Promise<string[]> {
  const found: string[] = [];
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(600);
  const text = await page.locator("body").innerText().catch(() => "");
  for (const t of FORBIDDEN_TEXT) if (text.includes(t)) found.push(`текст «${t}»`);
  for (const m of markers) if (text.includes(m)) found.push(`демо-объект «${m}»`);
  for (const id of FORBIDDEN_TESTIDS) if (await page.getByTestId(id).count()) found.push(`элемент data-testid=${id}`);
  return found;
}

test.describe.configure({ mode: "serial" });

test("рыночный режим: ни на одной странице App.tsx у настоящих учёток нет демо", async ({ browser }) => {
  test.setTimeout(30 * 60_000);
  const all = appRoutes();
  expect(all.length, "разбор App.tsx не нашёл маршрутов").toBeGreaterThan(50);
  const markers = demoMarkers();
  const tokens: Record<Role, string | null> = {
    anon: null, candidate: await realToken("candidate"), employer: await realToken("employer"),
    fsp: process.env.E2E_FSP_TOKEN || null,
  };
  const findings: { role: Role; page: string; found: string[] }[] = [];
  let pages = 0;
  for (const role of ["anon", "candidate", "employer", "fsp"] as Role[]) {
    if (role === "fsp" && !tokens.fsp) { console.log("[e2e] E2E_FSP_TOKEN не задан — роль ФСП пропущена"); continue; }
    const ctx = await browser.newContext({ baseURL: BASE_URL, serviceWorkers: "block", locale: "ru-RU" });
    await ctx.addInitScript((tok) => {
      localStorage.setItem("draft_cookie_consent", "essential");
      localStorage.removeItem("jury_scenario");
      localStorage.removeItem("fsp_jury_guide");
      if (tok) localStorage.setItem("fsp_token", tok);
    }, tokens[role]);
    const page = await ctx.newPage();
    for (const p of rolePages(all, role)) {
      pages += 1;
      const found = await scanPage(page, p, markers);
      if (found.length) findings.push({ role, page: p, found });
    }
    await ctx.close();
  }
  fs.mkdirSync("reports", { recursive: true });
  fs.writeFileSync("reports/market_mode.json", JSON.stringify({ pages, routes: all.length, findings }, null, 2));
  console.log(`[e2e] рыночный режим: страниц ${pages}, находок ${findings.length}`);
  expect(findings, findings.map((f) => `${f.page} [${f.role}]: ${f.found.join(", ")}`).join("\n")).toEqual([]);
});
