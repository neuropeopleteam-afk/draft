// Конвертер разряда ФСП → априорный буст θ₀ адаптивного теста, вес T2 в ранжировании и зарплатная премия в ₽.
// Один выбор достижения — три осязаемых эффекта. Числа — модель платформы (байесовский старт 2PL IRT) и офферы рынка.
import { useState } from "react";
import { NB } from "./ui";

interface Rank {
  id: string; title: string; short: string;
  theta0: number; minutes: number; start: string; weight: number; bypass: boolean; premium: [number, number];
}

const BASE_MINUTES = 35;
const RANKS: Rank[] = [
  { id: "regional", title: "Участник регионального кубка", short: "Региональный кубок", theta0: 0.3, minutes: 29, start: "Junior+", weight: 3, bypass: false, premium: [15_000, 25_000] },
  { id: "rank23", title: "2–3 спортивный разряд", short: "2–3 разряд", theta0: 0.6, minutes: 22, start: "Middle", weight: 5, bypass: true, premium: [35_000, 45_000] },
  { id: "kms", title: "1 разряд и КМС", short: "1 разряд / КМС", theta0: 0.9, minutes: 16, start: "Middle+", weight: 8, bypass: true, premium: [45_000, 55_000] },
  { id: "prize", title: "Призёр Чемпионата или Кубка России по продуктовому программированию", short: "Призёр ЧР / КР", theta0: 1.2, minutes: 12, start: "Middle+ / Senior", weight: 10, bypass: true, premium: [55_000, 65_000] },
];
const MARKET: [number, number] = [35_000, 65_000];  // коридор прибавки разрядникам ФСП по рынку, ₽/мес на руки
const SCALE = 75_000;

const k = (v: number) => `${(v / 1000).toLocaleString("ru-RU")}${NB}000${NB}₽`;
const t = (v: number) => `+${v.toLocaleString("ru-RU", { minimumFractionDigits: 1 })}`;

/** Две кривые априорного распределения θ: без ФСП N(0; 1) и с разрядом N(θ₀; 0,8). */
function Prior({ shift }: { shift: number }) {
  const W = 260, H = 70, x = (v: number) => ((v + 3) / 6) * W;
  const curve = (mu: number, sd: number) => {
    const pts: string[] = [];
    for (let i = 0; i <= 60; i++) {
      const v = -3 + (6 * i) / 60, y = Math.exp(-((v - mu) ** 2) / (2 * sd * sd));
      pts.push(`${x(v).toFixed(1)},${(H - 8 - y * (H - 16)).toFixed(1)}`);
    }
    return pts.join(" ");
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full" role="img" aria-label={`Старт теста смещён на θ₀ = ${t(shift)}`}>
      <line x1={0} x2={W} y1={H - 8} y2={H - 8} stroke="#310F53" strokeOpacity={0.15} />
      <polyline points={curve(0, 1)} fill="none" stroke="#8A83D1" strokeWidth={1.5} strokeDasharray="4 3" />
      <polyline points={curve(shift, 0.8)} fill="none" stroke="#E0004C" strokeWidth={2.25} />
      <line x1={x(shift)} x2={x(shift)} y1={6} y2={H - 8} stroke="#E0004C" strokeOpacity={0.4} />
      <text x={x(0)} y={H} fontSize={8} textAnchor="middle" fill="#5F57B8">0</text>
      <text x={Math.min(W - 14, x(shift))} y={H} fontSize={8} textAnchor="middle" fill="#E0004C">θ₀</text>
    </svg>
  );
}

export default function FspRankConverter({ embedded = false }: { embedded?: boolean }) {
  const [id, setId] = useState(RANKS[3].id);
  const r = RANKS.find((x) => x.id === id)!;
  const saved = BASE_MINUTES - r.minutes;
  const body = (
    <>
      <div>
        <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand">Конвертер разряда ФСП</p>
        <h2 className="mt-0.5 text-lg font-bold text-brand-night">Что спортивное достижение даёт в найме</h2>
      </div>
      <div className="grid gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Достижение ФСП">
        {RANKS.map((x) => (
          <button key={x.id} type="button" role="radio" aria-checked={x.id === id} onClick={() => setId(x.id)} title={x.title}
            className={`rounded-xl border px-3 py-2 text-left text-xs font-semibold leading-snug transition-colors ${x.id === id ? "border-brand-strong bg-brand-blush/40 text-brand-night" : "border-brand-night/10 text-brand-plum/85 hover:bg-brand-blush/20"}`}>
            {x.short}
          </button>
        ))}
      </div>
      <p className="text-xs text-brand-ink/65">{r.title} · подтверждается в паспорте ФСП по официальному реестру федерации.</p>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand-lavender">1 · Адаптивный старт теста</p>
          <p className="mt-1.5 text-2xl font-extrabold tabular-nums text-brand-night" title={`Смещение стартовой оценки θ₀ = ${t(r.theta0)}`}>Старт {r.start}</p>
          <Prior shift={r.theta0} />
          <p className="text-xs leading-relaxed text-brand-ink/75">
            Тест сразу начинает с задач уровня <b>{r.start}</b>: <b>{BASE_MINUTES} → {r.minutes}{NB}мин</b> (−{saved}{NB}мин, меньше лёгких вопросов).
          </p>
        </div>
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand-lavender">2 · Вес ФСП в ранжировании</p>
          <p className="mt-1.5 text-2xl font-extrabold tabular-nums text-brand-night">+{r.weight}{NB}%</p>
          <div className="mt-2 h-2 rounded-full bg-brand-night/10" aria-hidden="true">
            <div className="h-2 rounded-full bg-brand-strong transition-all" style={{ width: `${r.weight * 10}%` }} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">
            к индексу соответствия в подборке работодателя.{" "}
            {r.bypass ? <b className="text-emerald-700">Обход фильтра резюме: ✓</b> : <span>Фильтр резюме — на общих условиях.</span>}
          </p>
        </div>
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand-lavender">3 · Прибавка к вилке</p>
          <p className="mt-1.5 text-xl font-extrabold tabular-nums text-brand-night">+{k(r.premium[0])} — +{k(r.premium[1])}</p>
          <div className="relative mt-2 h-2 rounded-full bg-brand-night/10" aria-hidden="true">
            <div className="absolute inset-y-0 rounded-full bg-brand-lavender/40" style={{ left: `${(MARKET[0] / SCALE) * 100}%`, width: `${((MARKET[1] - MARKET[0]) / SCALE) * 100}%` }} />
            <div className="absolute inset-y-0 rounded-full bg-brand-strong transition-all" style={{ left: `${(r.premium[0] / SCALE) * 100}%`, width: `${((r.premium[1] - r.premium[0]) / SCALE) * 100}%` }} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">
            ₽/мес на руки в офферах. Коридор рынка для разрядников ФСП — <b>+35{NB}000 — +65{NB}000{NB}₽</b>.
          </p>
        </div>
      </div>
      <p className="text-[11px] text-brand-ink/55">Разряд сдвигает только старт теста: итоговый уровень считается по ответам, достижение не заменяет проверку.</p>
    </>
  );
  if (embedded) return <div className="space-y-4" data-testid="fsp-rank-converter">{body}</div>;
  return <section className="card space-y-4" aria-label="Конвертер разряда ФСП" data-testid="fsp-rank-converter">{body}</section>;
}
