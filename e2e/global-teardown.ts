/** После прогона: своя песочница удаляется (DELETE /api/jury/sandbox — всё, что создали тесты, уходит каскадом вместе
 * с учётками песочницы; пересоздание не нужно, следующий прогон создаст новую). Общее демо и чужие песочницы не
 * трогаем. E2E_KEEP_STATE=1 — оставить как есть; E2E_RESET=1 — прежнее поведение: сброс в исходное состояние. */
import { apiContext, deleteSandbox, resetSandbox } from "./lib/stand";

export default async function globalTeardown() {
  const sid = process.env.E2E_SCENARIO;
  if (!sid) return;  // global-setup не дошёл до песочницы — убирать нечего
  if (process.env.E2E_KEEP_STATE === "1") {
    console.log(`[e2e] E2E_KEEP_STATE=1 — песочница ${sid} оставлена как есть (продолжить: E2E_SCENARIO=${sid})`);
    return;
  }
  const api = await apiContext();
  try {
    if (process.env.E2E_RESET === "1") {
      await resetSandbox(api, sid);
      console.log(`[e2e] песочница ${sid} возвращена в исходное состояние`);
    } else {
      const out = await deleteSandbox(api, sid);
      console.log(out.skipped ? `[e2e] песочница ${sid} уже отсутствует` : `[e2e] песочница ${sid} удалена (${out.deleted_users} учёток, ${out.seconds} с)`);
    }
  } finally {
    await api.dispose();
  }
}
