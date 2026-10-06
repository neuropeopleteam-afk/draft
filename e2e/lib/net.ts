/**
 * Устойчивость к сети между раннером и стендом.
 *
 * Из нашей песочницы (исходящий прокси в AWS) до стенда в Москве заметная доля TCP-соединений с крупным ответом
 * обрывается после первых ~16 КБ: данные перестают приходить, соединение висит. С самого сервера те же файлы
 * отдаются без сбоев за 0,05 с, то есть это канал, а не приложение. Браузер такое соединение не перезапрашивает:
 * бандл SPA (400 КБ) не догружается, страница не открывается.
 *
 * Поэтому для удалённого стенда GET-запросы к его origin идут через route.fetch с тайм-аутом и повтором
 * (идемпотентные запросы повторять безопасно), а неизменяемые файлы сборки (/assets/*, имена с хешем) скачиваются
 * один раз за прогон и дальше отдаются из памяти. POST, PUT, DELETE не трогаем: они уходят из браузера как есть
 * и ровно один раз. Против локального стека слой выключен. Управление: E2E_NET_RETRY=1|0.
 */
import type { APIResponse, BrowserContext } from "@playwright/test";
import { BASE_URL } from "./stand";

const base = new URL(BASE_URL);
const isLocal = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])$/.test(base.hostname);
export const NET_RETRY = process.env.E2E_NET_RETRY ? process.env.E2E_NET_RETRY === "1" : !isLocal;

// обычная загрузка самого крупного файла (бандл 400 КБ) — около 1 с; оборванное соединение ждать дольше незачем
const ATTEMPT_TIMEOUTS_MS = [5_000, 5_000, 6_000, 8_000, 10_000, 12_000, 15_000, 20_000, 30_000];

export const netStats = { proxied: 0, retried: 0, failed: 0, cached: 0 };

interface Cached { status: number; headers: Record<string, string>; body: Buffer }
const immutable = new Map<string, Cached>();

export async function installNetRetry(ctx: BrowserContext): Promise<void> {
  if (!NET_RETRY) return;
  await ctx.route((url) => url.origin === base.origin, async (route) => {
    const req = route.request();
    const method = req.method();
    if (method !== "GET" && method !== "HEAD") return route.continue();
    const url = new URL(req.url());
    const isAsset = url.pathname.startsWith("/assets/");
    const hit = isAsset ? immutable.get(url.pathname) : undefined;
    if (hit) {
      netStats.cached++;
      return route.fulfill(hit).catch(() => undefined);
    }
    netStats.proxied++;
    for (const [i, timeout] of ATTEMPT_TIMEOUTS_MS.entries()) {
      let response: APIResponse;
      try {
        response = await route.fetch({ timeout, maxRedirects: 0 });
        const body = await response.body();
        // тело уже распаковано — заголовки сжатия и длины исходного ответа к нему не относятся
        const headers = Object.fromEntries(Object.entries(response.headers())
          .filter(([k]) => !["content-encoding", "content-length", "transfer-encoding"].includes(k.toLowerCase())));
        const entry = { status: response.status(), headers, body };
        if (isAsset && response.status() === 200) immutable.set(url.pathname, entry);
        return await route.fulfill(entry);
      } catch (e) {
        if (/closed|disposed|already handled/i.test(String(e))) return;  // страница уже закрыта
        if (i < ATTEMPT_TIMEOUTS_MS.length - 1) netStats.retried++;
      }
    }
    netStats.failed++;
    await route.abort("timedout").catch(() => undefined);
  });
}
