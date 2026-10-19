import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { NB } from "../ui";
import { DEMO, type DemoCandidate } from "./demoData";

/** W2: «Обратный драфт в действии (Show, Don't Tell)» — правый блок первого экрана главной. Переключатель направлений,
 *  карточка верифицированного кандидата (три колонки доказанности, бейдж ФСП, ползунок вилки, пробное приглашение)
 *  и превью устной защиты с ИИ-интервьюером. Всё на клиенте, без запросов: это пример интерфейса, данные условные. */
const money = (v: number) => v.toLocaleString("ru-RU").replace(/\s/g, NB);
type Flow = "idle" | "sent" | "viewed" | "accepted";

export function ReverseDraftDemo({ onTry }: { onTry: () => void; onLiveAvatar?: () => void; busyLive?: boolean }) {
  const [i, setI] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const c = DEMO[i];
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + DEMO.length) % DEMO.length;
    setI(n); tabs.current[n]?.focus();
  }
  return (
    <div className="np-glass np-glass-accent relative p-4 sm:p-5" role="region" aria-label="Обратный драфт в действии: пример интерфейса">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="np-eyebrow">Обратный драфт в действии</p>
        <span className="np-chip">Живой интерфейс</span>
      </div>
      <div role="tablist" aria-label="Направление" onKeyDown={onKey} className="np-tabs mt-3">
        {DEMO.map((d, k) => (
          <button key={d.key} ref={(el) => { tabs.current[k] = el; }} type="button" role="tab" id={`dir-tab-${d.key}`}
            aria-selected={k === i} aria-controls="dir-panel" tabIndex={k === i ? 0 : -1}
            onClick={() => setI(k)} className="np-tab">{d.tab}</button>
        ))}
      </div>
      <div id="dir-panel" role="tabpanel" aria-labelledby={`dir-tab-${c.key}`} className="mt-3">
        <CandidateCard key={c.key} c={c} onTry={onTry} />
      </div>
      <p className="mt-3 text-[11px] np-faint">Демонстрация интерфейса · профиль специалиста обезличен до согласия</p>
    </div>
  );
}

function CandidateCard({ c, onTry }: { c: DemoCandidate; onTry: () => void }) {
  const [from, setFrom] = useState(c.salary.from);
  const [flow, setFlow] = useState<Flow>("idle");
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);
  const to = from + c.salary.spread;
  const pos = (from - c.salary.min) / (c.salary.max - c.salary.spread - c.salary.min);
  const fit = pos >= 0.45 ? { t: "Сильное предложение для этой категории", k: "np-ok" } : pos >= 0.25 ? { t: "Рабочее предложение", k: "np-accent" } : { t: "Ниже обычного для категории — ответ менее вероятен", k: "np-risk" };
  function invite() {
    if (flow !== "idle") { onTry(); return; }
    setFlow("sent");
    timers.current.push(window.setTimeout(() => setFlow("viewed"), 1100), window.setTimeout(() => setFlow("accepted"), 2400));
  }
  const pct = Math.round(Math.max(0, Math.min(1, pos)) * 100);
  return (
    <article className="np-card p-4" aria-label={`Кандидат ${c.ref}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="np-avatar-ref" aria-hidden="true">{c.ref.slice(2)}</span>
          <div className="min-w-0">
            <p className="font-mono text-xs np-faint">{c.ref} · обезличен</p>
            <p className="font-bold leading-tight np-text">{c.title}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="np-badge np-badge-indigo">{c.grade}</span>
          <span className="np-badge np-badge-ok">Топ-{c.top}{NB}%</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Стек">
        {c.stack.map((s) => <span key={s} className="np-chip np-chip-sm">{s}</span>)}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Proof tone="ok" title="Подтверждено тестом IRT и реестром ФСП" items={c.proved} />
        <Proof tone="indigo" title="Косвенно проверено" items={c.indirect} />
        <Proof tone="calm" title="Риск: 0 сигналов" items={c.risk} />
      </div>

      <p className="np-cup mt-3">
        <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="9" r="5" /><path d="M8.5 13l-1.5 8 5-2.5 5 2.5-1.5-8" strokeLinejoin="round" /></svg>
        <span><b>Призёр Кубка ФСП</b> <span className="np-muted">· {c.cup}</span></span>
      </p>

      <div className="mt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <label htmlFor={`salary-${c.key}`} className="text-xs font-semibold uppercase tracking-[0.12em] np-faint">Ваше предложение</label>
          <output htmlFor={`salary-${c.key}`} className="text-lg font-extrabold tabular-nums np-text" data-testid="demo-salary">{money(from)}{NB}– {money(to)}{NB}₽</output>
        </div>
        <input id={`salary-${c.key}`} type="range" className="np-range mt-2 w-full" min={c.salary.min} max={c.salary.max - c.salary.spread} step={c.salary.step}
          value={from} onChange={(e) => { setFrom(Number(e.target.value)); if (flow !== "idle") setFlow("idle"); }}
          style={{ ["--np-fill" as string]: `${pct}%` }} aria-valuetext={`от ${money(from)} до ${money(to)} рублей`} />
        <p className={`mt-1.5 text-xs font-semibold ${fit.k}`}>{fit.t}</p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className="np-btn-primary px-5 py-2.5 text-sm" onClick={invite} data-testid="demo-invite">
          {flow === "idle" ? "Попробовать пригласить" : "Запустить демо"}
        </button>
        <FlowLine flow={flow} />
      </div>
    </article>
  );
}

function Proof({ tone, title, items }: { tone: "ok" | "indigo" | "calm"; title: string; items: string[] }) {
  return (
    <div className={`np-proof ${tone === "ok" ? "np-proof-ok" : tone === "indigo" ? "np-proof-indigo" : "np-proof-calm"}`}>
      <p className="text-[11px] font-bold uppercase leading-snug tracking-[0.08em]">{title}</p>
      <ul className="mt-1.5 space-y-1 text-xs leading-snug np-muted">
        {items.map((t) => <li key={t} className="flex gap-1.5"><span aria-hidden="true" className="np-proof-dot" />{t}</li>)}
      </ul>
    </div>
  );
}

function FlowLine({ flow }: { flow: Flow }) {
  if (flow === "idle") return <span className="text-xs np-muted">Вилка в рублях — обязательна. Контакты — после согласия.</span>;
  const steps: [Flow, string][] = [["sent", "Приглашение отправлено"], ["viewed", "Кандидат видит вилку"], ["accepted", "Принято — контакты открыты"]];
  const at = steps.findIndex(([f]) => f === flow);
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs" role="status" aria-live="polite">
      {steps.map(([f, t], k) => (
        <li key={f} className={`inline-flex items-center gap-1.5 ${k <= at ? "np-ok font-semibold" : "np-faint"}`}>
          <span className={`np-flow-dot ${k <= at ? "np-flow-dot-on" : ""}`} aria-hidden="true" />{t}
        </li>
      ))}
    </ol>
  );
}
