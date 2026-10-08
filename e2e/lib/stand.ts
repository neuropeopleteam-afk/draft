/** Обращения к API стенда вне браузера: проверка готовности, песочница жюри прогона, токены демо-персон.
 *
 * Песочницы жюри (backend/app/modules/jury/scope.py): вход POST /api/jury/login {persona, scenario: "new"}
 * создаёт свой набор демо-персон, дальше все входы прогона идут с её id (scenario). Сброс POST /api/jury/reset —
 * только с токеном демо-персоны и только своей песочницы. Один прогон = одна песочница: общее демо и песочницы
 * других экспертов жюри тесты не трогают.
 */
import { request, type APIRequestContext } from "@playwright/test";

export const BASE_URL = (process.env.E2E_BASE_URL || "http://127.0.0.1:8140").replace(/\/$/, "");

export type Persona = "candidate" | "candidate_nofsp" | "candidate_junior" | "candidate_new" | "employer" | "expert" | "fsp";

export async function apiContext(): Promise<APIRequestContext> {
  const user = process.env.E2E_BASIC_USER;
  const password = process.env.E2E_BASIC_PASSWORD;
  return request.newContext({
    baseURL: BASE_URL,
    httpCredentials: user && password ? { username: user, password, origin: new URL(BASE_URL).origin } : undefined,
    timeout: 120_000,
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Ждём, пока API ответит {status: "ok"} (локальный стек после `docker compose up` поднимается не сразу). */
export async function waitHealthy(api: APIRequestContext, seconds = 120): Promise<Record<string, unknown>> {
  const until = Date.now() + seconds * 1000;
  let last = "";
  while (Date.now() < until) {
    try {
      const r = await api.get("/api/health");
      if (r.ok()) {
        const body = await r.json();
        if (body.status === "ok") return body;
        last = JSON.stringify(body);
      } else last = `HTTP ${r.status()}`;
    } catch (e) {
      last = String(e);
    }
    await sleep(2000);
  }
  throw new Error(`API ${BASE_URL}/api/health не готов за ${seconds} с: ${last}`);
}

/** id песочницы прогона: его выдаёт global-setup (или задан снаружи через E2E_SCENARIO). */
export function sandboxId(): string {
  const sid = process.env.E2E_SCENARIO;
  if (!sid || !/^[a-z0-9]{10}$/.test(sid)) throw new Error("Нет песочницы жюри прогона (E2E_SCENARIO): запуск без global-setup?");
  return sid;
}

interface JuryLoginOut { access_token: string; scenario: string | null; shared: boolean; created?: boolean; persona: Persona }

async function login(api: APIRequestContext, persona: Persona, scenario: string): Promise<JuryLoginOut> {
  for (let attempt = 0; ; attempt++) {
    const r = await api.post("/api/jury/login", { data: { persona, scenario } });
    // 503 jury_not_ready — учётки песочницы ещё создаются в соседнем запросе
    if (r.status() === 503 && attempt < 10) { await sleep(3000); continue; }
    if (!r.ok()) throw new Error(`Вход жюри ${persona}: HTTP ${r.status()} ${await r.text()}`);
    return r.json();
  }
}

/** Новая песочница прогона. Если лимит новых песочниц исчерпан, API пускает в общее демо — его не трогаем: ошибка. */
export async function createSandbox(api: APIRequestContext): Promise<{ sid: string; created: boolean }> {
  const r = await login(api, "candidate", "new");
  if (r.shared || !r.scenario) {
    throw new Error("Стенд выдал общее демо вместо своей песочницы (лимит новых песочниц с адреса — 12 в час). " +
      "Общее демо тесты не трогают: повторите позже или задайте E2E_SCENARIO=<id своей песочницы>.");
  }
  return { sid: r.scenario, created: !!r.created };
}

/** Токен демо-персоны в песочнице прогона; ответ обязан быть из этой же песочницы. */
export async function juryToken(api: APIRequestContext, persona: Persona, sid = sandboxId()): Promise<string> {
  const r = await login(api, persona, sid);
  if (r.shared || r.scenario !== sid) throw new Error(`Вход ${persona}: ожидалась песочница ${sid}, получено ${r.scenario ?? "общее демо"}`);
  return r.access_token;
}

/** Сброс своей песочницы в исходное состояние. Повторный сброс раньше паузы — 429: ждём и повторяем. */
export async function resetSandbox(api: APIRequestContext, sid = sandboxId()): Promise<Record<string, unknown>> {
  for (let attempt = 0; attempt < 6; attempt++) {
    const token = await juryToken(api, "candidate", sid);  // после сброса учётки пересозданы — токен каждый раз новый
    const r = await api.post("/api/jury/reset", { headers: { Authorization: `Bearer ${token}` }, timeout: 180_000 });
    if (r.ok()) {
      const out = await r.json();
      if (out.moved || out.scenario !== sid) throw new Error(`Сброс: ожидалась песочница ${sid}, ответ ${JSON.stringify(out).slice(0, 200)}`);
      return out;
    }
    if (r.status() === 429) {
      const msg = JSON.stringify(await r.json().catch(() => ({})));
      const sec = Number(/через (\d+)/.exec(msg)?.[1] ?? 20);
      await sleep((sec + 1) * 1000);
      continue;
    }
    throw new Error(`Сброс песочницы ${sid}: HTTP ${r.status()} ${await r.text()}`);
  }
  throw new Error("Сброс песочницы: пауза между сбросами не закончилась");
}

/** Удаление своей песочницы без пересоздания (DELETE /api/jury/sandbox): дешевле сброса — прогон убирает за собой
 * так (<внутренний документ>, п. 9). Если учётки песочницы уже удалены по лимиту — делать нечего. */
export async function deleteSandbox(api: APIRequestContext, sid = sandboxId()): Promise<Record<string, unknown>> {
  let token: string;
  try { token = await juryToken(api, "candidate", sid); }
  catch (e) { return { ok: true, skipped: true, reason: String(e).slice(0, 200) }; }
  const r = await api.delete("/api/jury/sandbox", { headers: { Authorization: `Bearer ${token}` }, timeout: 180_000 });
  if (!r.ok()) throw new Error(`Удаление песочницы ${sid}: HTTP ${r.status()} ${await r.text()}`);
  const out = await r.json();
  if (out.scenario !== sid) throw new Error(`Удаление: ожидалась песочница ${sid}, ответ ${JSON.stringify(out).slice(0, 200)}`);
  return out;
}

export async function apiGet<T = any>(api: APIRequestContext, path: string, token: string): Promise<T> {
  const r = await api.get(`/api${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok()) throw new Error(`GET ${path}: HTTP ${r.status()} ${await r.text()}`);
  return r.json();
}
