/**
 * Чек-лист экспертов 20.10, п. 3 «правильный ответ в примере теста»: по сети, как у пользователя, — ответы всех экранов
 * с заданием ДО ответа не содержат ключа: полей answer, key, correct, expected, solution (и производных — correct_index,
 * expected_output, answer_key…), а JS-бандл сайта не содержит данных заданий с ответами.
 *
 * Поверхности: тест на грейд (/api/assessment/sessions: старт и текущее задание), кубки кандидата и работодателя
 * (/api/candidate/cups/{id}/start, /api/employer/cups/{id}), мини-тест живого зала (/api/jury/live/j/{code}/start, /me),
 * «Полигон» (/api/warroom/scenarios/{id}). Ответы проверяются целиком, рекурсивно. Поле «key» у служебных справочников
 * (вкладки, фильтры) — не ключ задания, поэтому «key» считается нарушением только внутри объекта-задания (есть
 * prompt/question/stem/options/code_lines/statement/body). Исключение одно — уже после ответа: у организатора кубка
 * (/api/employer/cups/{id}) поле solutions — присланные решения участников с итогом автопроверки.
 *
 * Поле с пустым значением (null, "", []) — не утечка: экран кубка отдаёт ещё не данный ответ кандидата как answer: null.
 *
 * Итог — reports/no_answer_keys.json: какие поверхности проверены (метод, путь, код ответа), находки (путь в JSON, поле).
 */
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { apiContext, BASE_URL, juryToken } from "../lib/stand";

const BAD = /^(answers?|answer_key|answer_id|answer_index|correct(_\w+)?|is_correct|expected(_\w+)?|solution(s)?|key)$/i;
const ITEM_HINT = ["prompt", "question", "stem", "options", "code_lines", "statement", "body", "choices"];

type Finding = { surface: string; path: string; field: string };
const findings: Finding[] = [];
const checked: { surface: string; method: string; url: string; status: number }[] = [];

// После ответа данные о проверке законны: у организатора кубка — присланные решения участников с итогом автопроверки.
const AFTER_ANSWER = new Set(["employer_cups:$.solutions"]);

function scan(surface: string, v: unknown, path = "$"): void {
  if (Array.isArray(v)) { v.forEach((x, i) => scan(surface, x, `${path}[${i}]`)); return; }
  if (!v || typeof v !== "object") return;
  const o = v as Record<string, unknown>;
  const itemLike = ITEM_HINT.some((k) => k in o);
  for (const [k, x] of Object.entries(o)) {
    if (AFTER_ANSWER.has(`${surface}:${path}.${k}`)) continue;
    // пустое поле (null, "", []) ключа не несёт: так экран кубка отдаёт ещё не данный ответ кандидата — answer: null
    const empty = x === null || x === undefined || x === "" || (Array.isArray(x) && x.length === 0);
    if (BAD.test(k) && !empty && (k.toLowerCase() !== "key" || itemLike)) findings.push({ surface, path: `${path}.${k}`, field: k });
    scan(surface, x, `${path}.${k}`);
  }
}

async function hit(api: any, surface: string, method: "get" | "post", url: string, opts: Record<string, unknown> = {}) {
  const r = await api[method](url, { timeout: 120_000, ...opts });
  checked.push({ surface, method: method.toUpperCase(), url: url.replace(/[0-9a-f-]{36}/g, "<id>"), status: r.status() });
  const ct = r.headers()["content-type"] || "";
  const body = ct.includes("json") ? await r.json().catch(() => null) : null;
  if (r.ok() && body !== null) scan(surface, body);
  return { status: r.status(), body };
}

const H = (t: string) => ({ headers: { Authorization: `Bearer ${t}` } });

test("ключи заданий не уходят на клиент: API экранов с заданием до ответа и JS-бандл", async () => {
  test.setTimeout(10 * 60_000);
  const api = await apiContext();
  const cand = await juryToken(api, "candidate_new");  // без категории: тест на грейд с нуля
  const graded = await juryToken(api, "candidate");     // с категорией: ему открыты кубки
  const emp = await juryToken(api, "employer");

  await test.step("тест на грейд: старт и текущее задание", async () => {
    const s = await hit(api, "assessment", "post", "/api/assessment/sessions",
      { ...H(cand), data: { claimed_grade: "middle", direction: "backend", mode: "express", integrity_ack: true } });
    expect([200, 201], `старт теста: ${JSON.stringify(s.body).slice(0, 300)}`).toContain(s.status);
    const id = s.body?.id ?? s.body?.session_id ?? s.body?.session?.id;
    expect(id, "в ответе старта есть номер сессии").toBeTruthy();
    await hit(api, "assessment", "get", `/api/assessment/sessions/${id}`, H(cand));
  });

  await test.step("кубки: кандидат (список, карточка, старт) и работодатель", async () => {
    const lst = await hit(api, "cups", "get", "/api/candidate/cups", H(graded));
    const items: any[] = lst.body?.items ?? (Array.isArray(lst.body) ? lst.body : []);
    expect(items.length, "кандидату с категорией доступен хотя бы один кубок").toBeGreaterThan(0);
    for (const c of items.slice(0, 2)) {
      await hit(api, "cups", "get", `/api/candidate/cups/${c.id}`, H(graded));
      await hit(api, "cups", "post", `/api/candidate/cups/${c.id}/join`, H(graded));
      await hit(api, "cups", "post", `/api/candidate/cups/${c.id}/start`, H(graded));
    }
    const el = await hit(api, "employer_cups", "get", "/api/employer/cups", H(emp));
    const eitems: any[] = el.body?.items ?? (Array.isArray(el.body) ? el.body : []);
    for (const c of eitems.slice(0, 2)) await hit(api, "employer_cups", "get", `/api/employer/cups/${c.id}`, H(emp));
  });

  await test.step("живой зал: мини-тест гостя без регистрации", async () => {
    const room = await hit(api, "jury_live", "post", "/api/jury/live/room", H(emp));
    expect(room.status, `зал: ${JSON.stringify(room.body).slice(0, 200)}`).toBe(200);
    const code = room.body.code;
    await hit(api, "jury_live", "get", `/api/jury/live/j/${code}`);
    const st = await hit(api, "jury_live", "post", `/api/jury/live/j/${code}/start`, { data: { direction: "backend" } });
    expect([200, 201], `мини-тест: ${JSON.stringify(st.body).slice(0, 200)}`).toContain(st.status);
    const gt = st.body?.guest_token ?? st.body?.token;
    if (gt) await hit(api, "jury_live", "get", `/api/jury/live/j/${code}/me`, { headers: { "X-Guest-Token": gt } });
  });

  await test.step("«Полигон»: сценарии до ответа", async () => {
    const l = await hit(api, "warroom", "get", "/api/warroom/scenarios", H(cand));
    const sc: any[] = l.body?.items ?? l.body?.scenarios ?? (Array.isArray(l.body) ? l.body : []);
    for (const s of sc.slice(0, 5)) await hit(api, "warroom", "get", `/api/warroom/scenarios/${s.id ?? s.scenario_id}`, H(cand));
  });

  const bundle: { file: string; hits: string[] }[] = [];
  await test.step("JS-бандл: нет данных заданий с ответами", async () => {
    const html = await (await api.get("/")).text();
    const files = [...new Set([...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.js)"/g)].map((m) => m[1]))];
    // ленивые чанки: ссылки на /assets/*.js внутри уже найденных файлов
    for (let i = 0; i < files.length && i < 400; i++) {
      const js = await (await api.get(files[i])).text();
      for (const m of js.matchAll(/["'`(,]\/?assets\/([\w.-]+\.js)/g)) if (!files.includes(`/assets/${m[1]}`)) files.push(`/assets/${m[1]}`);
      // поле-ответ с литеральным значением рядом с полем задания — это данные, а не код интерфейса
      const rx = /\{[^{}]{0,400}\b(?:prompt|question|stem|options|code_lines)\s*:[^{}]{0,400}\b(correct(?:_\w+)?|answer(?:_\w+)?|expected(?:_\w+)?|solution)\s*:\s*(?:"[^"]*"|'[^']*'|\d+|\[[^\]]*\]|!0|true)/g;
      const hits = [...js.matchAll(rx)].map((m) => m[1]);
      if (hits.length) bundle.push({ file: files[i], hits: [...new Set(hits)] });
    }
    checked.push({ surface: "bundle", method: "GET", url: `/assets/*.js (${files.length} файлов)`, status: 200 });
  });

  fs.mkdirSync("reports", { recursive: true });
  fs.writeFileSync("reports/no_answer_keys.json", JSON.stringify({ base_url: BASE_URL, at: new Date().toISOString(),
    checked, findings, bundle }, null, 1));
  const surfaces = new Set(checked.filter((c) => c.status < 300).map((c) => c.surface));
  expect([...surfaces].sort(), "проверены все поверхности").toEqual(["assessment", "bundle", "cups", "employer_cups", "jury_live", "warroom"]);
  expect(findings, "поля ключа в ответах API до ответа").toEqual([]);
  expect(bundle, "данные заданий с ответами в JS-бандле").toEqual([]);
});
