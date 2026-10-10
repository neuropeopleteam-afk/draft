// Тонкий клиент к backend. Все запросы идут на тот же origin (/api), в dev — через прокси Vite.
export type Role = "candidate" | "employer" | "admin" | "expert" | "fsp_analyst";

export interface UserOut { id: string; email: string; role: Role; is_email_verified: boolean; created_at: string }
export interface TokenOut { access_token: string; token_type: string; expires_in: number; user: UserOut }
/** Пароль (ссылка, один клик) принят, входа ещё нет: нужен код из приложения или обязательное подключение второго фактора. */
export interface TwoFactorChallenge {
  second_factor_required: true; pending_token: string; expires_in: number; setup_required: boolean; methods: string[];
  email: string; role: Role; landing?: string | null; persona?: string | null; scenario?: string | null; shared?: boolean | null;
}
export type AuthResult = TokenOut | TwoFactorChallenge;
export const isChallenge = (r: unknown): r is TwoFactorChallenge => !!r && typeof r === "object" && (r as any).second_factor_required === true;
export interface RegisterOut { user_id: string; email: string; role: Role; email_verification_required: boolean; dev_verification_code: string | null }
export interface CandidateProfile {
  full_name: string | null; phone: string | null; telegram: string | null; city: string | null;
  work_format: string; relocation: boolean; experience_years: number | string | null; salary_min_hidden: number | null;
  current_category_id: string | null; current_grade_id: string | null; current_direction_id: string | null;
  rating_score: number | null; grade_locked_until: string | null; visible_to_employers: boolean;
  privacy: Record<string, boolean>; public_ref: string | null; onboarding_completed_at: string | null;
  roles: string[]; fsp_id_claimed: string | null; jury_mode: boolean;
  specializations?: any[];
  age_group: string; parental_consent: boolean; parental_consent_at: string | null;
}
export interface Company {
  id: string; name: string; inn: string | null; industry: string | null; description: string | null;
  website: string | null; city: string | null; contact_email: string | null; contact_phone: string | null;
}
export interface MeOut {
  id: string; email: string; role: Role; is_email_verified: boolean; created_at: string;
  candidate: CandidateProfile | null;
  employer: { full_name: string | null; position: string | null; company: Company | null } | null;
  fsp: { linked: boolean; link_source: string | null; achievements_count: number } | null;
}
export interface Catalog {
  directions: { id: string; title: string; description: string }[];
  grades: { id: string; title: string; level: number; description: string }[];
  categories: { id: string; title: string; direction_id: string; grade_id: string; market_salary_from: number; market_salary_to: number }[];
  stack_tags: { id: string; title: string; kind: string; direction_id: string | null }[];
}

export class ApiError extends Error {
  /** retryAfterS — заголовок Retry-After ответа в секундах (503 db_busy, 429), иначе null (Я16). */
  constructor(public status: number, public code: string, message: string, public retryAfterS: number | null = null) { super(message); }
}

/** Retry-After в секундах (число или HTTP-дата), иначе null. */
export function retryAfterOf(res: Response): number | null {
  const v = res.headers.get("Retry-After");
  if (!v) return null;
  const n = Number(v);
  if (Number.isFinite(n) && n >= 0) return n;
  const t = Date.parse(v);
  return Number.isFinite(t) ? Math.max(0, Math.round((t - Date.now()) / 1000)) : null;
}

/** Я16: сбой сети или сервера (5xx, обрыв, тайм-аут, 408/429), а не ответ «нельзя» (401/403/404): имеет смысл
 *  повторить, вход и введённые данные не сбрасывать. */
export function isTransient(e: unknown): boolean {
  if (e instanceof ApiError) return e.status >= 500 || e.status === 0 || e.status === 408 || e.status === 429;
  return e instanceof TypeError || (typeof DOMException !== "undefined" && e instanceof DOMException && (e.name === "AbortError" || e.name === "TimeoutError"));
}

const TOKEN_KEY = "fsp_token";
export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

function messageFrom(status: number, body: any): { code: string; message: string } {
  const d = body?.detail;
  if (d && typeof d === "object" && !Array.isArray(d) && d.message) return { code: d.code, message: d.message };
  if (Array.isArray(d)) {
    const first = d[0];
    const field = first?.loc?.slice(-1)[0];
    const raw = String(first?.msg ?? "Проверьте поля формы").replace(/^Value error, /, "");
    const fieldRu: Record<string, string> = { email: "Почта", password: "Пароль", code: "Код" };
    return { code: "validation_error", message: field && fieldRu[field] ? `${fieldRu[field]}: ${raw}` : raw };
  }
  // Строка от FastAPI: русская — показываем как есть, английская по умолчанию («Not Found») — по коду статуса
  if (typeof d === "string" && /[а-яё]/i.test(d)) return { code: "http_" + status, message: d };
  return { code: "http_" + status, message: STATUS_TEXT[status] ?? (status >= 500 ? "Сервис временно недоступен, повторите через минуту" : "Не удалось выполнить запрос") };
}

const STATUS_TEXT: Record<number, string> = {
  400: "Проверьте введённые данные",
  401: "Сессия истекла — войдите заново",
  403: "Нет доступа к этому разделу",
  404: "Не найдено: возможно, запись удалена или ссылка устарела",
  409: "Данные уже изменились — обновите страницу",
  413: "Файл слишком большой",
  422: "Проверьте поля формы",
  429: "Слишком много запросов — подождите минуту и повторите",
};

// Абсолютный адрес API от origin: если стенд открыт как https://логин:пароль@хост/ (базовая авторизация),
// относительный fetch унаследовал бы учётные данные из адреса страницы и браузер отклонил бы запрос.
export function apiUrl(path: string): string {
  return `${window.location.origin}/api${path}`;
}

async function fetchRetry(url: string, init: RequestInit, tries = 3, timeoutMs = 15000): Promise<Response> {
  for (let i = 0; ; i++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...init, signal: ctl.signal });
      if (res.ok || res.status < 500 || i >= tries - 1) { await res.clone().arrayBuffer(); return res; }
    } catch (e) {
      if (i >= tries - 1) throw e;
    } finally {
      clearTimeout(timer);
    }
  }
}

/** Хук обезличенной статистики прохождения (lib/study.ts): путь, статус и код ошибки — без тел запросов и ответов. */
let errorHook: ((path: string, status: number, code: string) => void) | null = null;
export const setApiErrorHook = (fn: typeof errorHook) => { errorHook = fn; };

export async function api<T>(path: string, opts: { method?: string; body?: unknown; auth?: boolean; token?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  // token — явный токен вместо сохранённого (промежуточный токен второго фактора, lib/twofa.ts)
  const token = opts.token ?? tokenStore.get();
  if (opts.auth !== false && token) headers.Authorization = `Bearer ${token}`;
  const method = opts.method ?? (opts.body !== undefined ? "POST" : "GET");
  const init: RequestInit = { method, headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined };
  // GET идемпотентен: при обрыве или зависании соединения повторяем (до 2 раз, таймаут 15 с).
  let res: Response;
  try { res = method === "GET" ? await fetchRetry(apiUrl(path), init) : await fetch(apiUrl(path), init); }
  catch (e) { errorHook?.(path, 0, "network"); throw e; }
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const { code, message } = messageFrom(res.status, body);
    errorHook?.(path, res.status, code);
    throw new ApiError(res.status, code, message, retryAfterOf(res));
  }
  return body as T;
}

/** Загрузка файла (multipart). */
export async function apiUpload<T>(path: string, file: File, field = "file"): Promise<T> {
  const fd = new FormData();
  fd.append(field, file);
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(apiUrl(path), { method: "POST", headers, body: fd });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const { code, message } = messageFrom(res.status, body);
    throw new ApiError(res.status, code, message);
  }
  return body as T;
}

/** Скачать файл с авторизацией (PDF-профиль). */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const token = tokenStore.get();
  const res = await fetch(apiUrl(path), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, "download_failed", "Не удалось скачать файл");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
