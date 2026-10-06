/** Перед прогоном: стенд отвечает, режим жюри включён, у прогона своя песочница жюри в исходном состоянии.
 * Новая песочница создаётся входом с scenario "new"; E2E_SCENARIO=<id> — продолжить заданную (она сбрасывается).
 * id передаётся тестам через process.env.E2E_SCENARIO и пишется в reports/sandbox.json (для разбора). */
import { mkdirSync, writeFileSync } from "node:fs";
import { apiContext, BASE_URL, createSandbox, resetSandbox, waitHealthy } from "./lib/stand";

export default async function globalSetup() {
  const api = await apiContext();
  try {
    const health = await waitHealthy(api);
    const page = await api.get("/");
    if (page.status() === 401) {
      throw new Error(`${BASE_URL} требует базовую авторизацию: задайте E2E_BASIC_USER и E2E_BASIC_PASSWORD`);
    }
    if (!page.ok()) throw new Error(`${BASE_URL}/ → HTTP ${page.status()}`);
    const status = await (await api.get("/api/jury/status")).json();
    if (!status.available) throw new Error("Режим жюри выключен (JURY_MODE_AVAILABLE=false)");
    if (!status.sandboxes) throw new Error("Стенд без песочниц жюри: эта версия e2e рассчитана на песочницы (main от 06.10)");
    const t0 = Date.now();
    let sid = process.env.E2E_SCENARIO;
    let how: string;
    if (sid) {
      await resetSandbox(api, sid);
      how = "заданная, сброшена";
    } else {
      const box = await createSandbox(api);
      sid = box.sid;
      how = box.created ? "новая" : "новая из запаса";
    }
    process.env.E2E_SCENARIO = sid;
    mkdirSync("reports", { recursive: true });
    writeFileSync("reports/sandbox.json", JSON.stringify({ base_url: BASE_URL, scenario: sid, at: new Date().toISOString() }, null, 2));
    console.log(`[e2e] ${BASE_URL}: API ${health.version ?? "?"}, песочница жюри ${sid} (${how}) за ` +
      `${((Date.now() - t0) / 1000).toFixed(1)} с`);
  } finally {
    await api.dispose();
  }
}
