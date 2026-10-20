import { Alert, Loading, NB, num, pct, signed, useApi } from "../ui";
import { ProvenanceLine, RetestVsTruth } from "./Provenance";
import { ScrollX } from "../A11y";
import { fmtNum, fmtPct, getExpertAgreement, getSprtVerdict } from "../../lib/numbers";

/** Первый экран /validation: «5 чисел, которые доказывают механику» (backend: app/modules/validation/headline.py).
 *  Каждое число — из расчёта с подписью мира; нет расчёта — нет числа. */

export type Signature = { world?: string; seed?: number; config_hash?: string; commit?: string; command?: string; generated_at?: string; n?: number };

export function SignatureLine({ s, className = "" }: { s?: Signature | null; className?: string }) {
  if (!s) return null;
  return (
    <p className={`text-[11px] leading-snug text-brand-ink/65 [overflow-wrap:anywhere] ${className}`} data-testid="world-signature">
      Мир: {s.world ?? "—"} · seed{NB}{s.seed ?? "—"} · конфигурация <code>{s.config_hash ?? "—"}</code> · коммит <code>{s.commit ?? "—"}</code>{s.command ? <> · <code>{s.command}</code></> : null}
    </p>
  );
}

const fmt = (v: number | null | undefined, f: string) => (f === "pct" ? pct(v) : f === "signed3" ? signed(v, 3) : num(v, 3));

export default function Headline() {
  const { data, error, loading } = useApi<any>("/validation/headline", []);
  const sprt = getSprtVerdict();
  const expAg = getExpertAgreement();
  if (loading) return <div className="mt-8"><Loading /></div>;
  if (error) return <div className="mt-8"><Alert>{error}</Alert></div>;
  if (!data || data.missing) return <div className="mt-8"><Alert kind="info">Ключевые числа ещё не посчитаны: make path-retest и make bench.</Alert></div>;
  return (
    <section id="headline" className="mt-8 scroll-mt-20" aria-labelledby="headline-t" data-testid="validation-headline">
      <h2 id="headline-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">5 чисел, которые доказывают механику</h2>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">{data.how_to_read}</p>
      <div
        id="sprt-verdict-summary"
        data-testid="sprt-verdict-headline"
        className="mt-4 rounded-2xl border border-emerald-500/35 bg-emerald-50/40 p-4"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <span className="chip bg-emerald-600/15 font-semibold text-emerald-950">
              Кросс-валидация (обучение N = {sprt.cross_validation.n_train_per_point}, отложенный контроль N = {sprt.cross_validation.n_test})
            </span>
            <h3 className="mt-1 font-display text-sm font-extrabold text-brand-night">
              Последовательный критерий SPRT (α = 0,02) + 1/3 кодовых заданий + трёхзначный вердикт и 15-мин доп. этап у порога
            </h3>
          </div>
          <code className="rounded bg-white/80 px-2 py-0.5 text-[11px] text-brand-ink/70">{sprt.recompute}</code>
        </div>
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-brand-night/10 bg-white p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-ink/55">
              Точность уверенного вердикта
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-2">
              <span className="font-display text-2xl font-extrabold tabular-nums text-brand-night">
                {fmtPct(sprt.precision_decided, 1)}
              </span>
              <span className="chip text-[11px] tabular-nums">
                уверенных {fmtPct(sprt.decided_share, 1)}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-brand-ink/75">
              95 % ДИ [{fmtPct(sprt.precision_decided_ci?.[0], 1)}; {fmtPct(sprt.precision_decided_ci?.[1], 1)}] · ложное
              подтверждение среди уверенных — <b>{fmtPct(sprt.false_confirm_decided, 2)}</b> · ср. время ~{sprt.minutes_mean} мин.
            </p>
          </div>
          <div className="rounded-xl border border-brand-night/10 bg-white p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-ink/55">
              Точный грейд (6 ступеней)
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-2">
              <span className="font-display text-2xl font-extrabold tabular-nums text-brand-night">
                {fmtPct(sprt.exact_far_from_cut, 1)}
              </span>
              <span className="chip text-[11px] tabular-nums">
                весь пул {fmtPct(sprt.exact_with_followup, 1)}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-brand-ink/75">
              Вдали от порога (|θ − порог| ≥ 0,45) — <b>{fmtPct(sprt.exact_far_from_cut, 1)}</b>; с 15-мин доп. этапом по
              всему пулу — <b>{fmtPct(sprt.exact_with_followup, 1)}</b>; в пределах ±1 ступени —{" "}
              <b>{fmtPct(sprt.within_1, 1)}</b> (грубых ошибок: {sprt.gross_error_count}).
            </p>
          </div>
          <div className="rounded-xl border border-brand-night/10 bg-white p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-ink/55">
              Повторяемость (Test–Retest)
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-2">
              <span className="font-display text-2xl font-extrabold tabular-nums text-brand-night">
                κw = {fmtNum(sprt.retest.kappa_w, 3)}
              </span>
              <span className="chip text-[11px] tabular-nums">N = {sprt.retest.n}</span>
            </div>
            <p className="mt-1 text-[11px] text-brand-ink/75">
              Две параллельные сессии на разных субпулах: согласованность вердикта{" "}
              <b>{fmtPct(sprt.retest.verdict_consistency, 1)}</b>, совпадение ±1 ступень{" "}
              <b>{fmtPct(sprt.retest.within_1, 1)}</b>, r(θ₁, θ₂) = {fmtNum(sprt.retest.r_theta, 3)}.
            </p>
          </div>
          <div className="rounded-xl border border-brand-night/10 bg-white p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-ink/55">
              Согласие с экспертами (2 компании)
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-2">
              <span className="font-display text-2xl font-extrabold tabular-nums text-brand-night">
                κw = {fmtNum(expAg.cross_vendor_surrogate.platform_vs_consensus_kappa_w, 3)}
              </span>
              <span className="chip text-[11px] tabular-nums">
                точно {fmtPct(expAg.cross_vendor_surrogate.platform_vs_consensus_exact, 1)}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-brand-ink/75">
              Слепая разметка двумя моделями разных компаний (Anthropic + Google, N = 40, κw между ними{" "}
              {fmtNum(expAg.cross_vendor_surrogate.inter_model_kappa_w, 3)}) и ревизия 414 меток E1–E3 от 07.10 (κw = 0,916;
              суррогат до пилота с живыми экспертами).
            </p>
          </div>
        </div>
      </div>
      <AccuracyViews v={data.accuracy} className="mt-4" />
      <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {data.items.map((it: any, i: number) => (
          <li key={it.id} className="card flex min-w-0 flex-col" data-testid={`headline-${it.id}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{i + 1}. {it.title}</p>
            <p className="mt-2 text-3xl font-extrabold tabular-nums text-brand-night">{fmt(it.value, it.format)}</p>
            {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {fmt(it.ci[0], it.format)} … {fmt(it.ci[1], it.format)}</p>}
            {it.pair && <p className="text-xs tabular-nums text-brand-ink/70">nDCG@10: {num(it.pair[0], 3)} против {num(it.pair[1], 3)}</p>}
            <p className="mt-2 text-sm leading-snug text-brand-ink/80">{it.text}</p>
            {it.note && <p className="mt-1 text-xs text-brand-ink/65">{it.note}</p>}
            {it.protocol_note && <p className="mt-1 text-xs text-brand-ink/65" data-testid="headline-protocol-note">{it.protocol_note}</p>}
            <div className="mt-auto pt-3">
              <a href={`#${it.anchor}`} className="text-sm font-semibold text-brand-plum underline">Подробнее в разделе</a>
              <ProvenanceLine p={it.provenance} className="mt-1.5" />
              <SignatureLine s={it.signature} className="mt-1" />
            </div>
          </li>
        ))}
      </ol>
      <RetestVsTruth v={data.retest_vs_truth} className="mt-3" />
      <Protocols v={data.protocols} className="mt-3" />
    </section>
  );
}

/** Д5: сверка двух протоколов с одним порогом P — перебор правил (make grade-sweep: числа docs/NUMBERS.json и слайдов)
 *  и контрольный прогон всего пути с настройками продукта (make path-retest: числа карточек выше). */
export function Protocols({ v, className = "" }: { v?: any; className?: string }) {
  if (!v) return null;
  const rows: [string, any][] = [[`Перебор правил, P${NB}≥${NB}${v.sweep?.confirm_level} (make grade-sweep)`, v.sweep], [`Весь путь, P${NB}≥${NB}${v.path?.confirm_level} (make path-retest, карточки)`, v.path]];
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-protocols">
      <p className="text-sm font-semibold leading-snug text-brand-night">Два протокола, один порог</p>
      <ScrollX label="Сверка протоколов" className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Перебор правил и повтор всего пути при одном пороге уверенности</caption>
          <thead className="text-xs text-brand-ink/70">
            <tr>{["Протокол", "Точно", "Выше истинного", "Повтор: совпало", "κw повтора", "Банк"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(([k, x]) => (
              <tr key={k} className="border-t border-brand-night/5 tabular-nums">
                <th scope="row" className="px-2 py-1 font-medium text-brand-night">{k}</th>
                <td className="px-2 py-1">{pct(x?.exact, 1)}</td><td className="px-2 py-1">{pct(x?.over, 1)}</td>
                <td className="px-2 py-1">{pct(x?.retest_exact, 1)}</td><td className="px-2 py-1">{num(x?.retest_kappa, 3)}</td>
                <td className="px-2 py-1"><code>{String(x?.bank ?? "—").slice(0, 8)}</code>{x?.bank_families ? ` · ${x.bank_families} семейств` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">{v.text}</p>
    </div>
  );
}

/** W1: точность грейда — три прозрачных числа первыми (make accuracy-views): вдали от порога, без занижения заявки,
 *  строго по всему пулу (+ повтор). У каждого — кто входит и доля пула. */
export function AccuracyViews({ v, className = "" }: { v?: any; className?: string }) {
  if (!v?.items?.length) return null;
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-accuracy">
      <p className="text-sm font-semibold leading-snug text-brand-night">Точность грейда: три числа, у каждого — кто входит</p>
      <ol className="mt-3 grid gap-3 md:grid-cols-3">
        {v.items.map((it: any, i: number) => (
          <li key={it.id} className="min-w-0 rounded-xl bg-[#F7F6FC] p-3" data-testid={`accuracy-${it.id}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{"абв"[i]}) {it.title}</p>
            <p className="mt-1 text-2xl font-extrabold tabular-nums text-brand-night">{pct(it.value, 1)}</p>
            {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {pct(it.ci[0], 1)} … {pct(it.ci[1], 1)}</p>}
            <p className="mt-1 text-xs text-brand-ink/70">Кто входит: {it.who} · доля пула {pct(it.share, 1)}</p>
            <p className="mt-1.5 text-sm leading-snug text-brand-ink/80">{it.text}</p>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/70">{v.note} Пересчёт: <code>{v.command}</code>.</p>
      <ProvenanceLine p={v.provenance} className="mt-1.5" />
      <SignatureLine s={v.signature} className="mt-1" />
    </div>
  );
}
