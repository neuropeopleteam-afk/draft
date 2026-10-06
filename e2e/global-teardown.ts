/** После прогона: убираем всё, что создали тесты (пересдача, потребность, приглашение), — сброс демо жюри.
 * Сброс удаляет только учётки и компанию жюри (каскадом их сессии, подборки, приглашения) и создаёт их заново. */
import { apiContext, resetJury } from "./lib/stand";

export default async function globalTeardown() {
  if (process.env.E2E_KEEP_STATE === "1") {
    console.log("[e2e] E2E_KEEP_STATE=1 — демо жюри оставлено как есть; сброс: POST /api/jury/reset");
    return;
  }
  const api = await apiContext();
  try {
    await resetJury(api);
    console.log("[e2e] демо жюри возвращено в исходное состояние");
  } finally {
    await api.dispose();
  }
}
