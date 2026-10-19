// Н2: «Интерактивный пульт инцидента» — тренировочный сценарий к заданиям архитектурного и инцидентного типа
// (Middle и выше). Сервис платежей деградирует после релиза: p95 растёт со 110 до 1 890 мс, свободные соединения
// пула БД падают до 0, в логах — TimeoutError: QueuePool limit of size 10 overflow 20 reached. Кандидат находит
// строку-причину в коде релиза (внешний HTTP-вызов к шлюзу внутри транзакции БД) и выбирает исправление (вызов — за
// транзакцию, идемпотентный ключ). Сценарий целиком на клиенте и в балл не идёт: оценивается письменный ответ задания.
// Доступность: строки кода и решения — кнопки с aria-pressed (не radio/option — у задания свои элементы выбора),
// поток логов — без aria-live (не мешает чтению), итог шага — role="status"; prefers-reduced-motion — без анимации.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

const STEPS = 16;          // точек на графике (по одной в ~0,7 с), затем «плато» с лёгким дрожанием
const TICK_MS = 700;
const P95_FROM = 110, P95_TO = 1890, POOL = 10;

/** Код релиза 2026.10.17-3: 8 строк, причина — строка 5. */
const CODE = [
  `@router.post("/payments")`,
  `async def create_payment(body: PaymentIn, db: AsyncSession = Depends(get_db)):`,
  `    async with db.begin():`,
  `        order = await db.get(Order, body.order_id, with_for_update=True)`,
  `        resp = await gateway.charge(order.amount, card=body.card_token)  # до 30 с`,
  `        order.status = "paid" if resp.ok else "failed"`,
  `        db.add(Payment(order_id=order.id, gateway_id=resp.id))`,
  `    return {"status": order.status}`,
];
const CAUSE = 5;
const LINE_HINT: Record<number, string> = {
  1: "Маршрут не менялся с прошлого релиза — смотрите, что происходит внутри обработчика.",
  2: "Зависимость get_db выдаёт одно соединение на запрос — вопрос в том, как долго оно занято.",
  3: "Транзакция сама по себе нужна. Важно, что выполняется, пока она открыта.",
  4: "Блокировка строки заказа короткая — если внутри транзакции нет долгих операций.",
  6: "Присваивание статуса мгновенное — задержку даёт не оно.",
  7: "Вставка платежа — миллисекунды. Ищите операцию, которая ждёт внешнюю систему.",
  8: "Ответ клиенту отдаётся после фиксации транзакции — задержка возникает раньше.",
};
const CAUSE_TEXT = "Верно: строка 5 — HTTP-вызов к платёжному шлюзу внутри открытой транзакции. Пока шлюз отвечает (до 30 с), запрос держит соединение пула и блокировку строки заказа; 10 соединений и 20 сверх лимита заканчиваются за секунды — остальные запросы ждут в очереди и падают с TimeoutError.";

interface Fix { id: string; title: string; ok: boolean; why: string }
const FIXES: Fix[] = [
  { id: "pool", title: "Поднять пул до 50 соединений и таймаут до 60 секунд", ok: false,
    why: "Отодвинет отказ на минуты: соединения по-прежнему заняты ожиданием шлюза, а база упрётся в max_connections и заденет соседние сервисы." },
  { id: "move", title: "Вынести вызов шлюза за транзакцию и передавать идемпотентный ключ", ok: true,
    why: "Соединение занято миллисекунды: короткая транзакция «pending» → вызов шлюза без соединения → короткая транзакция с итогом. Ключ idempotency_key не даёт списать деньги дважды при повторе запроса или таймауте." },
  { id: "retry", title: "Повторять запрос к шлюзу до трёх раз внутри той же транзакции", ok: false,
    why: "Хуже: транзакция живёт втрое дольше, а без идемпотентного ключа повтор может списать деньги дважды." },
  { id: "rollback", title: "Откатить релиз и больше ничего не менять", ok: false,
    why: "Снимет симптом сегодня, но дефект вернётся со следующим релизом — причина в коде не устранена. Откат — первая мера, не решение." },
];
const FIXED_CODE = [
  `key = f"pay-{body.order_id}-{body.attempt_id}"  # идемпотентный ключ`,
  `async with db.begin():  # транзакция 1: миллисекунды`,
  `    order = await db.get(Order, body.order_id, with_for_update=True)`,
  `    order.status = "pending"`,
  `resp = await gateway.charge(order.amount, card=body.card_token, idempotency_key=key)`,
  `async with db.begin():  # транзакция 2: итог`,
  `    await finalize(db, order.id, resp)  # paid или failed + Payment`,
];

/** Задание похоже на архитектурное или инцидентное — показываем пульт (Middle и выше). */
const INCIDENT_RE = /(инцидент|сбой|деградац|отказ сервис|задержк|латентност|p95|p99|пул соединен|connection pool|транзакц|архитектур|масштабир|нагрузк|таймаут|timeout|SLO|отказоустойчив|узкое место|постмортем)/i;
export function isIncidentTask(it: { format?: string | null; stem?: string | null; step_prompt?: string | null } | null | undefined, grade?: string | null): boolean {
  if (!it || !["middle", "senior", "lead", "principal"].includes(String(grade ?? ""))) return false;
  const text = `${it.stem ?? ""} ${it.step_prompt ?? ""}`;
  return ["open_answer", "open_book_3step"].includes(String(it.format)) ? INCIDENT_RE.test(text) : /(инцидент|постмортем|пул соединен|QueuePool)/i.test(text);
}

const reduced = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const fmtMs = (v: number) => `${Math.round(v).toLocaleString("ru-RU")}\u00a0мс`;
const ease = (k: number) => 1 - Math.pow(1 - k, 2.2);

/** Значения метрик на шаге t (0…STEPS) и после исправления (fixedAt — шаг применения). */
function metrics(t: number, fixedAt: number | null) {
  const k = Math.min(1, t / (STEPS - 3));
  const jit = Math.sin(t * 2.3) * 0.035 + Math.cos(t * 1.7) * 0.02;
  let p95 = t === 0 ? P95_FROM : P95_FROM + (P95_TO - P95_FROM) * ease(k) * (k >= 1 ? 1 + jit : 1);
  let free = Math.max(0, Math.round(POOL * (1 - ease(Math.min(1, k * 1.35)))));
  let err = k < 0.45 ? 0.2 : 0.2 + 13.8 * ease((k - 0.45) / 0.55);
  if (fixedAt != null && t > fixedAt) {
    const r = Math.min(1, (t - fixedAt) / 4);
    p95 = p95 + (118 * (1 + jit) - p95) * ease(r);
    free = Math.round(free + (8 - free) * ease(r));
    err = err + (0.2 - err) * ease(r);
  }
  if (t >= STEPS - 3 && fixedAt == null) p95 = Math.min(1990, Math.max(1790, p95));
  return { p95, free, err };
}

const LOG_OK = (n: number, ms: number) => `INFO  POST /payments 200 ${ms}ms order=${48210 + n}`;
function logLine(t: number, i: number, fixed: boolean): { lvl: "info" | "warn" | "error"; text: string } {
  const m = metrics(t, null);
  if (fixed) return { lvl: "info", text: LOG_OK(t * 3 + i, 96 + ((t * 7 + i * 13) % 40)) };
  if (m.free > 4) return { lvl: "info", text: LOG_OK(t * 3 + i, Math.round(m.p95 * (0.7 + 0.1 * i))) };
  if (m.free > 0) return i === 0
    ? { lvl: "warn", text: `WARN  slow request POST /payments ${Math.round(m.p95)}ms — gateway.charge waited ${(m.p95 / 1000 * 0.92).toFixed(2)}s` }
    : { lvl: "info", text: LOG_OK(t * 3 + i, Math.round(m.p95 * 0.8)) };
  return i % 2 === 0
    ? { lvl: "error", text: "ERROR sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00" }
    : { lvl: "warn", text: `WARN  POST /payments 503 30012ms — pool checkout wait, in_use=30/30` };
}

function Spark({ values, max, label, tone, testid }: { values: number[]; max: number; label: string; tone: "bad" | "ok"; testid: string }) {
  const w = 220, h = 56;
  const pts = values.map((v, i) => [values.length < 2 ? w : (i / (STEPS + 6)) * w, h - 4 - (Math.min(v, max) / max) * (h - 10)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const col = tone === "bad" ? "#FF0053" : "#2BB673";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-10 w-full sm:h-14" role="img" aria-label={label} data-testid={testid} preserveAspectRatio="none">
      <line x1="0" x2={w} y1={h - 4} y2={h - 4} stroke="currentColor" strokeOpacity="0.15" />
      {pts.length > 1 && <path d={`${d} L${pts[pts.length - 1][0].toFixed(1)},${h - 4} L0,${h - 4} Z`} fill={col} fillOpacity="0.12" />}
      <path d={d} fill="none" stroke={col} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
      {pts.length > 0 && <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3.2" fill={col} />}
    </svg>
  );
}

function Metric({ title, value, sub, bad, children }: { title: string; value: string; sub: string; bad: boolean; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-white/5 p-2.5 ring-1 ring-white/10 sm:p-3">
      <p className="text-[10px] font-semibold uppercase leading-tight tracking-[0.1em] text-white/70 sm:text-[11px]">{title}</p>
      <p className={`mt-1 whitespace-nowrap text-base font-extrabold tabular-nums sm:text-2xl ${bad ? "text-[#FF6B98]" : "text-[#7BE0A8]"}`}>{value}</p>
      <p className="hidden text-xs text-white/65 sm:block">{sub}</p>
      <div className="mt-1 text-white">{children}</div>
    </div>
  );
}

export function IncidentSandbox({ className = "" }: { className?: string }) {
  const still = useMemo(reduced, []);
  const [t, setT] = useState(still ? STEPS : 0);
  const [paused, setPaused] = useState(false);
  const [line, setLine] = useState<number | null>(null);
  const [tries, setTries] = useState(0);
  const [fix, setFix] = useState<string | null>(null);
  const [fixTries, setFixTries] = useState(0);
  const [fixedAt, setFixedAt] = useState<number | null>(null);
  const logBox = useRef<HTMLDivElement | null>(null);
  const found = line === CAUSE;
  const chosen = FIXES.find((f) => f.id === fix) ?? null;
  const solved = !!chosen?.ok;
  const horizon = STEPS + 6;

  useEffect(() => {  // поток событий: метрики и логи — раз в ~0,7 с, после плато — «дыхание» на последних точках
    if (paused || still) return;
    const id = window.setInterval(() => setT((x) => (x >= horizon ? x : x + 1)), TICK_MS);
    return () => window.clearInterval(id);
  }, [paused, still, horizon]);
  useEffect(() => { if (still && solved) setT(horizon); }, [still, solved, horizon]);
  useEffect(() => { const b = logBox.current; if (b) b.scrollTop = b.scrollHeight; }, [t]);

  const series = useMemo(() => Array.from({ length: Math.min(t, horizon) + 1 }, (_, i) => metrics(i, fixedAt)), [t, fixedAt, horizon]);
  const now = series[series.length - 1];
  const logs = useMemo(() => {
    const out: { ts: string; lvl: "info" | "warn" | "error"; text: string }[] = [];
    for (let i = Math.max(0, t - 6); i <= Math.min(t, horizon); i++) {
      for (let j = 0; j < 2; j++) {
        const sec = 14 + i * 1 + j * 0.4;
        const ts = `12:04:${String(Math.floor(sec) % 60).padStart(2, "0")}.${String(Math.round((sec % 1) * 1000)).padStart(3, "0")}`;
        out.push({ ts, ...logLine(i, j, fixedAt != null && i > fixedAt + 1) });
      }
    }
    return out.slice(-10);
  }, [t, fixedAt, horizon]);

  function pickLine(n: number) {
    if (found) return;
    setLine(n); setTries((x) => x + 1);
  }
  function pickFix(f: Fix) {
    if (solved) return;
    setFix(f.id); setFixTries((x) => x + 1);
    if (f.ok) { setFixedAt(Math.min(t, horizon - 5)); setT((x) => Math.min(x, horizon - 5)); setPaused(false); }
  }
  function reset() { setT(still ? STEPS : 0); setLine(null); setTries(0); setFix(null); setFixTries(0); setFixedAt(null); setPaused(false); }

  const sev = solved ? "Восстановлен" : now.free === 0 ? "SEV-2 · отказ части платежей" : now.p95 > 400 ? "Деградация" : "Норма";
  const sevCls = solved ? "bg-[#2BB673] text-white" : now.free === 0 ? "bg-brand-strong text-white" : now.p95 > 400 ? "bg-amber-400 text-brand-ink" : "bg-white/15 text-white";

  return (
    <section aria-labelledby="incident-h" data-testid="incident-sandbox"
      className={`overflow-hidden rounded-2xl bg-[radial-gradient(130%_120%_at_100%_0%,#3a1561_0%,#1C1D22_60%)] text-white ring-1 ring-white/10 ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#FFD6E4]">Тренировочный сценарий · в балл не входит</p>
          <h2 id="incident-h" className="text-base font-extrabold tracking-tight sm:text-lg">Пульт инцидента: payments-api после релиза 2026.10.17-3</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${sevCls}`} data-testid="incident-sev">{sev}</span>
          {!still && <button type="button" onClick={() => setPaused((p) => !p)} aria-pressed={paused} className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold ring-1 ring-white/20 hover:bg-white/20">{paused ? "Продолжить поток" : "Пауза потока"}</button>}
        </div>
      </header>

      <div className="space-y-4 p-4">
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            <Metric title="Задержка p95" value={fmtMs(now.p95)} sub={`норма ${fmtMs(P95_FROM)}`} bad={now.p95 > 400}>
              <Spark values={series.map((m) => m.p95)} max={2100} tone={now.p95 > 400 ? "bad" : "ok"} testid="incident-p95"
                label={`Задержка p95: сейчас ${fmtMs(now.p95)}, до релиза ${fmtMs(P95_FROM)}`} />
            </Metric>
            <Metric title="Свободно в пуле БД" value={`${now.free} из ${POOL}`} sub="pool_size 10 · overflow 20" bad={now.free <= 2}>
              <Spark values={series.map((m) => m.free)} max={POOL} tone={now.free <= 2 ? "bad" : "ok"} testid="incident-pool"
                label={`Свободные соединения пула: ${now.free} из ${POOL}`} />
            </Metric>
            <Metric title="Ошибки 5xx" value={`${now.err.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}\u00a0%`} sub="240 запросов в секунду" bad={now.err > 1}>
              <Spark values={series.map((m) => m.err)} max={16} tone={now.err > 1 ? "bad" : "ok"} testid="incident-err"
                label={`Доля ошибок 5xx: ${now.err.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} процента`} />
            </Metric>
          </div>
          <p className="text-xs text-white/70">Релиз 2026.10.17-3 выкатан в 12:04:10 · изменения: обработчик POST /payments</p>
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-white/70">Логи payments-api, поток</p>
            <div ref={logBox} className="h-40 overflow-y-auto rounded-xl bg-black/40 p-2.5 font-mono text-[11.5px] leading-relaxed ring-1 ring-white/10" data-testid="incident-logs" tabIndex={0} aria-label="Поток логов сервиса платежей">
              {logs.map((l, i) => (
                <p key={`${l.ts}-${i}`} className={`whitespace-pre-wrap break-words ${l.lvl === "error" ? "text-[#FF6B98]" : l.lvl === "warn" ? "text-amber-300" : "text-white/75"}`}>
                  <span className="text-white/45">{l.ts}</span> {l.text}
                </p>
              ))}
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-3">
          <div>
            <p className="mb-1 text-sm font-semibold">Шаг 1. Нажмите строку релиза, которая вызвала инцидент</p>
            <div className="overflow-x-auto rounded-xl bg-black/40 py-2 ring-1 ring-white/10" aria-label="Код релиза: строки-кнопки" data-testid="incident-code">
              {CODE.map((ln, i) => {
                const n = i + 1;
                const sel = line === n;
                const cls = sel ? (n === CAUSE ? "bg-[#2BB673]/30 ring-1 ring-inset ring-[#2BB673]" : "bg-brand/30 ring-1 ring-inset ring-brand") : "hover:bg-white/10";
                return (
                  <button key={n} type="button" aria-pressed={sel} disabled={found && !sel} onClick={() => pickLine(n)} data-testid={`incident-line-${n}`}
                    className={`flex w-full items-start gap-3 px-3 text-left font-mono text-[12.5px] leading-6 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-white disabled:cursor-default ${cls}`}>
                    <span className="w-5 shrink-0 select-none text-right text-white/45">{n}</span>
                    <span className="whitespace-pre text-[#FFD6E4]">{ln}</span>
                  </button>
                );
              })}
            </div>
            {line != null && (
              <p role="status" data-testid="incident-line-verdict" className={`mt-2 rounded-xl px-3 py-2 text-sm ${found ? "bg-[#2BB673]/15 text-[#BFF0D4]" : "bg-brand/15 text-[#FFD6E4]"}`}>
                {found ? CAUSE_TEXT : `Строка ${line}: ${LINE_HINT[line]}`}
              </p>
            )}
          </div>

          {found && (
            <div>
              <p className="mb-1 text-sm font-semibold">Шаг 2. Выберите исправление</p>
              <div className="grid gap-2" role="group" aria-label="Варианты исправления">
                {FIXES.map((f) => {
                  const sel = fix === f.id;
                  return (
                    <button key={f.id} type="button" aria-pressed={sel} disabled={solved && !sel} onClick={() => pickFix(f)} data-testid={`incident-fix-${f.id}`}
                      className={`rounded-xl px-3 py-2 text-left text-sm font-semibold ring-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-white disabled:opacity-50 ${sel ? (f.ok ? "bg-[#2BB673]/25 ring-[#2BB673]" : "bg-brand/25 ring-brand") : "bg-white/5 ring-white/15 hover:bg-white/10"}`}>
                      {f.title}
                    </button>
                  );
                })}
              </div>
              {chosen && <p role="status" data-testid="incident-fix-verdict" className={`mt-2 rounded-xl px-3 py-2 text-sm ${chosen.ok ? "bg-[#2BB673]/15 text-[#BFF0D4]" : "bg-brand/15 text-[#FFD6E4]"}`}>{chosen.ok ? "Верно. " : "Не лучший выбор. "}{chosen.why}</p>}
            </div>
          )}

          {solved && (
            <div data-testid="incident-solved">
              <p className="mb-1 text-sm font-semibold">Исправленный обработчик</p>
              <pre className="overflow-x-auto rounded-xl bg-black/40 p-3 font-mono text-[12px] leading-6 text-[#BFF0D4] ring-1 ring-[#2BB673]/40"><code>{FIXED_CODE.join("\n")}</code></pre>
              <p className="mt-2 text-xs text-white/75">
                Разбор: причина найдена {tries === 1 ? "с первой попытки" : `с ${tries}-й попытки`}, решение — {fixTries === 1 ? "с первой" : `с ${fixTries}-й`}.
                Метрики возвращаются к норме: p95 около 120&nbsp;мс, свободно 8 из 10. Опишите в ответе к заданию, как бы вы это проверили и предотвратили — это и оценивается.
              </p>
            </div>
          )}
          <div className="flex justify-end">
            <button type="button" onClick={reset} className="text-xs font-semibold text-white/70 underline underline-offset-2 hover:text-white" data-testid="incident-reset">Сначала</button>
          </div>
        </div>
      </div>
    </section>
  );
}
