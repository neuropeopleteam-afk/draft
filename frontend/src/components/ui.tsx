import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { ApiError, api } from "../lib/api";

/** Неразрывный пробел: между числом и «₽»/«%», внутри «220 000». */
export const NB = "\u00A0";
/** 1234567 → «1 234 567 ₽» (разряды и знак рубля — неразрывными пробелами). */
export const rub = (v?: number | null) => (v ? `${v.toLocaleString("ru-RU")}${NB}₽` : "—");
export const range = (a?: number | null, b?: number | null) => (a || b ? `${a ? rub(a) : "…"}${NB}– ${b ? rub(b) : "…"}` : "—");
/** Число по-русски: десятичная запятая, минус «−», разряды. num(1.756) → «1,76». */
export const num = (v?: number | null, d = 2) => (v == null || Number.isNaN(Number(v)) ? "—"
  : Number(v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−"));
/** Со знаком: «+1,76», «−0,10». */
export const signed = (v?: number | null, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${num(v, d)}`);
/** Текст объяснений с сервера: «θ = 1.27 ± 0.49» → «θ = 1,27 ± 0,49», «260 000 ₽» — с неразрывными пробелами.
 *  Даты «06.10» и версии вида «v1.2» не трогает. */
export const ruText = (s?: string | null) => (s ?? "")
  .replace(/(^|[\s(=±+−-])(0|[1-9]\d{0,2})\.(\d+)(?![.\d])/g, "$1$2,$3")
  .replace(/(\d) (?=\d{3}(?!\d))/g, `$1${NB}`)
  .replace(/(\d) (₽|%|тыс\.)/g, `$1${NB}$2`);
/** Доля → проценты: 0.953 → «95 %». */
export const pct = (v?: number | null, d = 0) => (v == null ? "—" : `${num(v * 100, d)}${NB}%`);
export const dt = (s?: string | null) => (s ? new Date(s).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }) : "—");
/** Дата без времени (ГГГГ-ММ-ДД) — без сдвига часового пояса браузера: «6 октября 2026 г.». */
export function dateOnly(v?: string | null): string {
  const m = v ? /^(\d{4})-(\d{2})-(\d{2})/.exec(v) : null;
  if (!m) return dt(v ?? undefined);
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}
/** Дата в конце предложения: точку после «г.» ставит само предложение — «…с 8 октября 2026 г.» без «г..». */
export const dtEnd = (s?: string | null) => dt(s).replace(/\.$/, "");
export const dateOnlyEnd = (v?: string | null) => dateOnly(v).replace(/\.$/, "");
/** Склонение по числу: plural(1, "кандидат", "кандидата", "кандидатов") → «кандидат». */
export const plural = (n: number, one: string, few: string, many: string) => {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
};
export const dtt = (s?: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
export const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Не удалось связаться с сервером");

export const DIRECTIONS: Record<string, string> = { backend: "Backend", frontend: "Frontend", data_ml: "Data/ML", qa: "QA", security: "Информационная безопасность" };
// Грейды платформы снизу вверх (как GRADE_ORDER в backend/app/modules/catalog/seed_data.py)
export const GRADES: Record<string, string> = { intern: "Стажёр", junior: "Junior", middle: "Middle", senior: "Senior" };
// Грейд — уровень навыков, его подтверждает тест (ответ организаторов VS.1); стаж — только подсказка «обычно …»
// (как GRADE_SKILL_TEXT и GRADE_EXPERIENCE_TEXT на бэкенде)
export const GRADE_SKILLS: Record<string, string> = {
  intern: "Начинающий: базовые конструкции языка, простые задачи по образцу, учится читать чужой код",
  junior: "Решает типовые задачи по понятной постановке, знает основы инструментов, работает с наставником",
  middle: "Самостоятельно ведёт задачу от постановки до выпуска, находит дефекты в чужом коде, понимает устройство инструментов",
  senior: "Проектирует решения, выбирает компромиссы, находит неочевидные дефекты и объясняет их команде",
  lead: "Ведёт архитектуру системы и техническую работу команды: ревью дизайна, разбор инцидентов, миграции без простоя",
  principal: "Задаёт техническую стратегию нескольких команд: архитектура на годы, крупные миграции, стандарты и их цена",
};
// Короткая строка для карточки выбора грейда (Ф4: экран перед стартом короткий; полный текст — под «Что умеет каждый уровень»)
export const GRADE_SKILLS_SHORT: Record<string, string> = {
  intern: "Базовые конструкции, задачи по образцу",
  junior: "Типовые задачи по понятной постановке, с наставником",
  middle: "Сам ведёт задачу от постановки до выпуска",
  senior: "Проектирует решения, объясняет компромиссы команде",
  lead: "Архитектура системы и техническое лидерство команды",
  principal: "Техническая стратегия нескольких команд",
};
export const GRADE_EXPERIENCE: Record<string, string> = { intern: "обычно без опыта или до полугода", junior: "обычно до 1,5 лет опыта", middle: "обычно 1,5–4,5 года опыта", senior: "обычно от 4,5 лет опыта", lead: "обычно от 7,5 лет опыта", principal: "обычно от 10 лет опыта" };
// Lead и Principal (флаг GRADES_EXT_ENABLED на сервере): подписи и тексты выше есть всегда, а перебирать уровни нужно
// через useGrades (lib/grades.ts): без флага и в направлениях без проверенных семейств этих уровней их нет
export const GRADE_EXT: Record<string, string> = { lead: "Lead", principal: "Principal" };
export const GRADE_TITLE_ALL: Record<string, string> = { ...GRADES, ...GRADE_EXT };
export const catTitle = (id?: string | null) => {
  if (!id) return "Не присвоена";
  const [d, g] = id.split(".");
  return `${DIRECTIONS[d] ?? d} · ${GRADE_TITLE_ALL[g] ?? g}`;
};

/** Загрузка данных с повтором. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  // Быстрая смена направления/грейда: запоздавший ответ старого запроса не заменяет новую выдачу.
  const requestSeq = useRef(0);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const reload = useCallback(async () => {
    if (!path) return;
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const result = await api<T>(path);
      if (seq === requestSeq.current) { setData(result); setError(null); }
    }
    catch (e) { if (seq === requestSeq.current) setError(errText(e)); }
    finally { if (seq === requestSeq.current) setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { void reload(); return () => { requestSeq.current++; }; }, [reload]);
  return { data, error, loading, reload, setData };
}

const LEVEL_STYLE: Record<string, string> = {
  T2: "bg-brand-night text-white",
  T1: "bg-brand-strong text-white",  // brand чуть темнее: белый 12 px на #FF0053 — 3,9 : 1
  T0: "bg-brand-blush text-brand-plum",
  none: "bg-gray-100 text-gray-600",
};
const LEVEL_HINT: Record<string, string> = {
  T2: "Подтверждено реестром ФСП",
  T1: "Подтверждено тестом или зондом на платформе",
  T0: "Указано кандидатом, не проверено",
  none: "Нет данных",
};

export function Level({ level }: { level?: string | null }) {
  const l = level ?? "none";
  return (
    <span title={LEVEL_HINT[l]} aria-label={`${l === "none" ? "нет данных" : l}: ${LEVEL_HINT[l] ?? ""}`} className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-xs font-bold leading-none tracking-wide ${LEVEL_STYLE[l] ?? LEVEL_STYLE.none}`}>
      {l === "none" ? "нет" : l}
    </span>
  );
}

export function LevelLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-brand-ink/70">
      {["T1", "T2", "T0"].map((l) => <span key={l} className="inline-flex items-center gap-1.5"><Level level={l} />{LEVEL_HINT[l]}</span>)}
    </div>
  );
}

const STATUS: Record<string, [string, string]> = {
  sent: ["Отправлено", "bg-brand-blush text-brand-plum"],
  viewed: ["Просмотрено", "bg-[#ECEAF8] text-brand-night"],
  accepted: ["Принято", "bg-emerald-50 text-emerald-700"],
  declined: ["Отклонено", "bg-gray-100 text-gray-600"],
  withdrawn: ["Отозвано", "bg-gray-100 text-gray-500"],
  expired: ["Истекло", "bg-gray-100 text-gray-500"],
  submitted: ["Ответ получен", "bg-[#ECEAF8] text-brand-night"],
  reviewed: ["Оценено", "bg-emerald-50 text-emerald-700"],
  // встречное предложение и доступ к контактам (app.modules.contact): события истории без смены статуса
  counter_sent: ["Встречное предложение", "bg-amber-50 text-amber-800"],
  counter_accepted: ["Встречное принято", "bg-emerald-50 text-emerald-700"],
  counter_declined: ["Встречное отклонено", "bg-gray-100 text-gray-600"],
  counter_withdrawn: ["Встречное закрыто", "bg-gray-100 text-gray-500"],
  contacts_revoked: ["Доступ к контактам отозван", "bg-amber-50 text-amber-800"],
  contacts_restored: ["Доступ к контактам возвращён", "bg-emerald-50 text-emerald-700"],
  // найм после принятия (app.modules.hiring): события истории приглашения
  interview_proposed: ["Предложено время собеседования", "bg-[#ECEAF8] text-brand-night"],
  interview_moved: ["Собеседование переносится", "bg-amber-50 text-amber-800"],
  interview_reschedule: ["Кандидат просит другое время", "bg-amber-50 text-amber-800"],
  interview_scheduled: ["Собеседование назначено", "bg-[#ECEAF8] text-brand-night"],
  interview_done: ["Собеседование прошло", "bg-emerald-50 text-emerald-700"],
  interview_cancelled: ["Собеседование отменено", "bg-gray-100 text-gray-600"],
  offer_sent: ["Оффер отправлен", "bg-brand-blush text-brand-plum"],
  offer_counter: ["Встречное на оффер", "bg-amber-50 text-amber-800"],
  offer_counter_accepted: ["Встречное на оффер принято", "bg-emerald-50 text-emerald-700"],
  offer_counter_declined: ["Встречное на оффер отклонено", "bg-gray-100 text-gray-600"],
  offer_accepted: ["Оффер принят", "bg-emerald-50 text-emerald-700"],
  offer_declined: ["Оффер отклонён", "bg-gray-100 text-gray-600"],
  offer_withdrawn: ["Оффер отозван", "bg-gray-100 text-gray-500"],
  offer_expired: ["Срок ответа на оффер истёк", "bg-gray-100 text-gray-500"],
  hired: ["Вышел на работу", "bg-emerald-50 text-emerald-700"],
  hire_rejected: ["Не прошёл", "bg-gray-100 text-gray-600"],
  hire_declined: ["Отказ кандидата", "bg-gray-100 text-gray-600"],
};

export function Status({ s }: { s: string }) {
  const [t, c] = STATUS[s] ?? [s, "bg-gray-100 text-gray-600"];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${c}`}>{t}</span>;
}

export const statusTitle = (s: string) => STATUS[s]?.[0] ?? s;

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "ok"; children: ReactNode }) {
  if (!children) return null;
  const c = kind === "error" ? "border-brand/30 bg-brand-blush/40 text-brand-plum" : kind === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-brand-lavender/30 bg-[#F3F2FB] text-brand-night";
  return <div role={kind === "error" ? "alert" : "status"} className={`rounded-xl border px-4 py-3 text-sm ${c}`}>{children}</div>;
}

export function Loading({ text = "Загрузка…" }: { text?: string }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite" role="status">
      <span className="sr-only">{text}</span>
      <div className="h-6 w-1/3 animate-pulse rounded bg-brand-blush/60" />
      <div className="h-24 animate-pulse rounded-2xl bg-brand-blush/30" />
      <div className="h-24 animate-pulse rounded-2xl bg-brand-blush/30" />
    </div>
  );
}

export function Empty({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="card border-dashed px-6 py-10 text-center">
      <svg viewBox="0 0 24 24" className="mx-auto mb-3 h-8 w-8 text-brand-lavender" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <rect x="3.5" y="5" width="17" height="14" rx="3" /><path d="M3.5 13h5l1.5 2h4l1.5-2h5" />
      </svg>
      <p className="font-semibold text-brand-night">{title}</p>
      {text && <p className="mx-auto mt-1 max-w-md text-sm leading-relaxed text-brand-ink/70">{text}</p>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs leading-relaxed text-brand-ink/65">{hint}</p>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 py-2">
      <span>
        <span className="block text-sm font-medium text-brand-ink">{label}</span>
        {hint && <span className="block text-xs leading-relaxed text-brand-ink/65">{hint}</span>}
      </span>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="h-6 w-11 rounded-full bg-brand-night/15 transition-colors peer-checked:bg-brand peer-focus-visible:ring-2 peer-focus-visible:ring-brand peer-focus-visible:ring-offset-2" />
        <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5" />
      </span>
    </label>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="card min-w-0 break-words">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-xl font-bold tabular-nums text-brand-night">{value}</p>
      {hint && <p className="mt-1 text-xs leading-relaxed text-brand-ink/65">{hint}</p>}
    </div>
  );
}

/** Элементы окна, на которые попадает Tab (видимые и не выключенные). */
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
/** Tab и Shift+Tab ходят по кругу внутри окна (aria-modal): фокус не уходит на страницу под затемнением.
 *  С box = document.body — по кругу внутри страницы (тест: Tab после последней кнопки не уводит в адресную строку). */
export function trapTab(e: KeyboardEvent, box: HTMLElement | null) {
  if (e.key !== "Tab" || !box) return;
  const items = [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.getClientRects().length > 0);
  if (!items.length) { e.preventDefault(); box.focus(); return; }
  const first = items[0], last = items[items.length - 1], a = document.activeElement;
  if (!box.contains(a)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && (a === first || a === box)) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const titleId = useId();
  // Только при открытии/закрытии (onClose часто новая функция на каждый рендер — фокус не должен прыгать)
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); else trapTab(e, box.current); };
    window.addEventListener("keydown", h);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";  // фон под окном не прокручивается
    box.current?.focus({ preventScroll: true });
    return () => { window.removeEventListener("keydown", h); document.body.style.overflow = overflow; prev?.focus?.({ preventScroll: true }); };
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-brand-night/40 p-0 md:items-center md:p-6" onClick={onClose}>
      <div ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-t-2xl bg-white p-5 shadow-xl outline-none sm:p-6 md:rounded-2xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-lg font-bold text-brand-night">{title}</h2>
          <button onClick={onClose} className="-mr-1 -mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-brand-ink/65 hover:bg-brand-blush/50 hover:text-brand-night" aria-label="Закрыть">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function History({ items }: { items: { status: string; at: string; by?: string; note?: string | null }[] }) {
  return (
    <ol className="space-y-2 border-l-2 border-brand-blush pl-4">
      {items.map((e, i) => (
        <li key={i} className="text-sm">
          <span className="font-semibold text-brand-night">{statusTitle(e.status)}</span>
          <span className="text-brand-ink/65"> · {dtt(e.at)}{e.by ? ` · ${e.by === "candidate" ? "кандидат" : "работодатель"}` : ""}</span>
          {e.note && <p className="text-brand-ink/70">«{e.note}»</p>}
        </li>
      ))}
    </ol>
  );
}

/** Переключатель (radiogroup): в группе одна остановка Tab, выбор — стрелками, Home и End (как у радиокнопок). */
export function Seg<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { id: T; title: string }[]; label: string }) {
  const cur = Math.max(0, options.findIndex((o) => o.id === value));
  function onKey(e: ReactKeyboardEvent<HTMLDivElement>) {
    const step: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    const n = options.length;
    const i = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : e.key in step ? (cur + step[e.key] + n) % n : -1;
    if (i < 0 || !n) return;
    e.preventDefault();
    onChange(options[i].id);
    (e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[i])?.focus();
  }
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-xl bg-brand-blush/40 p-1" role="radiogroup" aria-label={label} onKeyDown={onKey}>
      {options.map((o, i) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id} tabIndex={i === cur ? 0 : -1} onClick={() => onChange(o.id)}
          className={`rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${value === o.id ? "bg-white text-brand-night shadow-sm" : "text-brand-plum/80 hover:text-brand-plum"}`}>
          {o.title}
        </button>
      ))}
    </div>
  );
}

/** «1 год», «3 года», «5 лет»; дробный стаж — «2,5 года». */
export function years(v: number | string | null | undefined): string {
  if (v == null || v === "") return "";
  const n = Number(v);
  if (!Number.isInteger(n)) return `${n.toLocaleString("ru-RU")} года`;
  const d10 = n % 10, d100 = n % 100;
  const w = d10 === 1 && d100 !== 11 ? "год" : d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14) ? "года" : "лет";
  return `${n} ${w}`;
}
