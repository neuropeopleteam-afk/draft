/** После прогона: своя песочница — в исходное состояние (всё, что создали тесты, удаляется каскадом вместе с
 * учётками песочницы и пересоздаётся). Общее демо и чужие песочницы не трогаем. E2E_KEEP_STATE=1 — оставить как есть. */
import { apiContext, resetSandbox } from "./lib/stand";

export default async function globalTeardown() {
  const sid = process.env.E2E_SCENARIO;
  if (!sid) return;  // global-setup не дошёл до песочницы — сбрасывать нечего
  if (process.env.E2E_KEEP_STATE === "1") {
    console.log(`[e2e] E2E_KEEP_STATE=1 — песочница ${sid} оставлена как есть (продолжить: E2E_SCENARIO=${sid})`);
    return;
  }
  const api = await apiContext();
  try {
    await resetSandbox(api, sid);
    console.log(`[e2e] песочница ${sid} возвращена в исходное состояние`);
  } finally {
    await api.dispose();
  }
}
