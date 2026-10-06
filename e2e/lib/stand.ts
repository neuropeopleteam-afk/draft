/** Обращения к API стенда вне браузера: проверка готовности, сброс демо жюри, токены демо-персон. */
import { request, type APIRequestContext } from "@playwright/test";

export const BASE_URL = (process.env.E2E_BASE_URL || "http://127.0.0.1:8140").replace(/\/$/, "");

export type Persona = "candidate" | "candidate_nofsp" | "employer" | "expert";

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

/** Сброс демо жюри в исходное состояние. На повторный сброс раньше паузы API отвечает 429 — ждём и повторяем. */
export async function resetJury(api: APIRequestContext): Promise<Record<string, unknown>> {
  for (let attempt = 0; attempt < 6; attempt++) {
    const r = await api.post("/api/jury/reset", { timeout: 180_000 });
    if (r.ok()) return r.json();
    if (r.status() === 429) {
      const msg = JSON.stringify(await r.json().catch(() => ({})));
      const sec = Number(/через (\d+)/.exec(msg)?.[1] ?? 20);
      await sleep((sec + 1) * 1000);
      continue;
    }
    throw new Error(`Сброс демо жюри: HTTP ${r.status()} ${await r.text()}`);
  }
  throw new Error("Сброс демо жюри: пауза между сбросами не закончилась");
}

export async function juryToken(api: APIRequestContext, persona: Persona): Promise<string> {
  const r = await api.post("/api/jury/login", { data: { persona } });
  if (!r.ok()) throw new Error(`Вход жюри ${persona}: HTTP ${r.status()} ${await r.text()}`);
  return (await r.json()).access_token;
}

export async function apiGet<T = any>(api: APIRequestContext, path: string, token: string): Promise<T> {
  const r = await api.get(`/api${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok()) throw new Error(`GET ${path}: HTTP ${r.status()} ${await r.text()}`);
  return r.json();
}
