/** Перед прогоном: стенд отвечает, режим жюри включён, демо жюри в исходном состоянии. */
import { apiContext, BASE_URL, resetJury, waitHealthy } from "./lib/stand";

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
    const t0 = Date.now();
    const out = await resetJury(api);
    console.log(`[e2e] ${BASE_URL}: API ${health.version ?? "?"}, демо жюри сброшено за ${((Date.now() - t0) / 1000).toFixed(1)} с` +
      ` (удалено учёток: ${out.deleted_users ?? "?"})`);
  } finally {
    await api.dispose();
  }
}
