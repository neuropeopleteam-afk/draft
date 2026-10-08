// Живая демонстрация для жюри (идея 13): API зала, гостя и экрана, сигналы на телефоне.
import { num as uiNum, signed } from "../../components/ui";
import { ApiError, apiUrl } from "../../lib/api";

export interface Opt { id: string; text: string; code?: string | null }
export interface LiveItem {
  token: string; position: number; total: number; format: string; block: string; stem: string;
  code: string | null; language: string | null; options: Opt[] | null; answer_kind: "option" | "line"; time_limit_s: number;
}
export interface Reason { requirement: string; level: string; status: string; text: string }
export interface TopRow {
  ref: string; rank: number; score: number; category_id: string | null; label: string | null;
  is_guest: boolean; is_self: boolean; fsp: boolean; mini: boolean; theta: number | null; se: number | null;
}
export interface Guest {
  id?: string; number: number; label: string; ref: string; direction: string; direction_title: string;
  stage: "testing" | "done" | "selected" | "invited" | "accepted" | "declined" | "no_category";
  answered: number; total: number; created_at: string; finished_at: string | null;
  item?: LiveItem | null;
  result: null | {
    theta: number; se: number; grade: string | null; category_id: string | null; category_title: string | null;
    preliminary?: boolean; ceiling?: string; capped?: boolean;
    correct: number; answered: number; time_s: number; skills: { tag: string; title: string; score: number }[];
  };
  selection: null | {
    need_title: string; version: number; rank: number | null; total: number; score: number | null;
    reasons: Reason[]; components: Record<string, number>; selected_at: string | null; top?: TopRow[];
  };
  invite: null | {
    position_title: string; salary_from: number; salary_to: number; sent_at: string | null; responded_at: string | null;
    market: { from: number; to: number; median: number | null } | null; viewed: boolean;
    push: { devices: number; delivered: number; at: string } | null;
    offer_description?: string; evidence?: { level: string; kind: string; text: string }[]; contact_method?: string;
    status?: string; company?: { name: string; industry: string | null; city: string | null } | null;
    trust?: { score: number; level: string; level_title: string; preliminary: boolean; summary: string;
      offer_salary: { status: string; text: string } | null } | null;
  };
}
export interface RoomPublic {
  code: string; company: string; open: boolean; items: number; rule: string;
  push: { enabled: boolean; vapid_public_key: string | null };
  directions: { id: string; title: string; need: string }[];
}
export interface RoomOut {
  code: string; url: string; qr_svg: string; qr_png: string; rule: string; company: string; items: number;
  push: { enabled: boolean; vapid_public_key: string | null };
}
export interface LiveEvent { at: string; kind: string; guest: number; label: string; ref: string; text: string }
export interface Feed extends RoomOut {
  changed: true; rev: number; now: string; guests: Guest[]; events: LiveEvent[]; rule: string;
  counters: Record<"joined" | "testing" | "finished" | "with_category" | "selected" | "invited" | "accepted" | "declined" | "push_delivered", number>;
  next_reveal_at: string | null;
}

const KEY = (code: string) => `jury_live_guest_${code}`;
export const guestToken = {
  get: (code: string) => localStorage.getItem(KEY(code)),
  set: (code: string, t: string) => localStorage.setItem(KEY(code), t),
  clear: (code: string) => localStorage.removeItem(KEY(code)),
};

/** Запрос гостя: без JWT, с токеном гостя из этого браузера. */
export async function guestApi<T>(code: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const t = guestToken.get(code);
  if (t) headers["X-Guest-Token"] = t;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(apiUrl(`/jury/live/j/${code}${path}`), {
    method: body !== undefined ? "POST" : "GET", headers, body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "omit", cache: "no-store",
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    throw new ApiError(res.status, d?.code ?? `http_${res.status}`, d?.message ?? (res.status >= 500 ? "Сервис временно недоступен" : "Ошибка запроса"));
  }
  return data as T;
}

export const FORMAT_TITLE: Record<string, string> = {
  find_bug: "Найдите строку с дефектом", choose_fix: "Выберите исправление", mcq_concept: "Вопрос на понимание",
};
export const STAGE_TITLE: Record<string, string> = {
  testing: "проходит мини-тест", done: "тест завершён", selected: "в подборке", invited: "приглашён",
  accepted: "принял приглашение", declined: "отклонил", no_category: "без категории",
};
export const time = (s?: string | null) =>
  s ? new Date(s).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
// θ и погрешность — теми же num/signed, что экран итога теста и карточка (ui.tsx): одно округление, «+1,40 ± 0,72»
export const num = (v?: number | null, d = 2) => signed(v, d);
export const plain = (v?: number | null, d = 2) => uiNum(v, d);

// ------------------------------------------------------------------ сигнал о приглашении без push
let ctx: AudioContext | null = null;

/** Разблокировать звук: вызывается из обработчика нажатия (политика автозапуска браузеров, iOS). */
export function unlockAudio() {
  try {
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return;
    ctx = ctx ?? new AC();
    if (ctx.state === "suspended") void ctx.resume();
    const o = ctx.createOscillator(); const g = ctx.createGain();
    g.gain.value = 0.0001; o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.02);
  } catch { /* без звука — останутся вибрация и заголовок вкладки */ }
}

/** Короткий двухтоновый сигнал + вибрация (Android) + заголовок вкладки. */
export function chime(title = "Приглашение · Встречный") {
  try {
    if (ctx) {
      const t0 = ctx.currentTime;
      [[880, 0], [1320, 0.16]].forEach(([f, dt]) => {
        const o = ctx!.createOscillator(); const g = ctx!.createGain();
        o.type = "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t0 + dt); g.gain.exponentialRampToValueAtTime(0.25, t0 + dt + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.35);
        o.connect(g).connect(ctx!.destination); o.start(t0 + dt); o.stop(t0 + dt + 0.4);
      });
    }
  } catch { /* звук недоступен */ }
  try { navigator.vibrate?.([180, 90, 180]); } catch { /* нет вибрации (iPhone) */ }
  const prev = document.title;
  if (!prev.startsWith(title)) {
    document.title = `${title} — ${prev}`;
    setTimeout(() => { document.title = prev; }, 15_000);
  }
}
