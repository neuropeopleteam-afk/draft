import type { ReactNode } from "react";
import { Alert, DIRECTIONS, Loading, useApi } from "../ui";

/** Блок /validation: стабильность статуса «Junior (предварительно)» на симуляции теста
 *  (backend: app/modules/validation/junior_stability.py, make stability). */

const pct = (v?: number | null) => (v == null ? "—" : `${Math.round(v * 100)}\u00A0%`);
const intRu = (v?: number | null) => (v == null ? "—" : v.toLocaleString("ru-RU"));
const n1 = (v?: number | null) => (v == null ? "—" : v.toFixed(1).replace(".", ","));
const n2 = (v?: number | null) => (v == null ? "—" : v.toFixed(2).replace(".", ","));

export default function JuniorStability() {
  const { data: r, error, loading } = useApi<any>("/validation/junior-stability", []);
  return (
    <section id="junior" className="mt-12 scroll-mt-20" aria-labelledby="junior-t">
      <h2 id="junior-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Junior у порога: статус «предварительно»</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Расчёт ещё не выполнен: запустите make stability.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const app = r.total?.app ?? {};
  const leg = r.total?.legacy_sim ?? {};
  const b = app.before ?? {};
  const a = app.after ?? {};
  const c = app.confirm ?? {};
  const last = c.attempts?.[c.attempts.length - 1];
  const dirs = Object.entries<any>(r.directions ?? {});
  const row = (title: string, before: ReactNode, after: ReactNode, legacy?: ReactNode): ReactNode[] => [title, before, after, legacy ?? ""];
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Те же {intRu(r.n_per_direction)} симулированных кандидатов на направление и те же сессии текущего теста, что в разделе «Тест»; меняется только правило решения по θ̂ и SE у порога Junior.
        «До» — подтверждён от P = {pct(r.rule?.confirm_level)}, иначе отказ без категории. «После» — то же подтверждение, а при P(θ ≥ порога) от {pct(r.rule?.provisional_level)} до {pct(r.rule?.confirm_level)} — «Junior (предварительно)»: кандидат остаётся в категории Junior со штрафом к скору, работодатель видит вероятность.
        Истинный уровень известен симуляции (θ истинное), поэтому ошибки считаются точно.
      </p>
      <div className="mt-4"><Alert kind="info"><b>Честно: </b>{r.caveat}</Alert></div>

      <div className="mt-6 grid gap-4 md:grid-cols-4">
        <Kpi label="Предварительных среди заявивших Junior" value={pct(a.share?.provisional)} hint={`${intRu(a.provisional)} из ${intRu(a.n_claimed_junior)} по ${dirs.length} направлениям`} />
        <Kpi label="Ложные отказы: до → после" value={`${pct(b.false_rejected_share)} → ${pct(a.false_rejected_share)}`} hint={`истинный уровень не ниже Junior, категории нет: ${intRu(b.false_rejected)} → ${intRu(a.false_rejected)} из ${intRu(a.n_true_junior_or_above)}`} />
        <Kpi label="Ложных предварительных" value={pct(a.false_provisional_share)} hint={`истинный уровень ниже порога: ${intRu(a.false_provisional)} из ${intRu(a.provisional)} предварительных`} />
        <Kpi label="После дотестирования остаётся предварительных" value={last ? pct(last.still_provisional / Math.max(c.n_provisional, 1)) : "—"} hint={last ? `${intRu(last.still_provisional)} из ${intRu(c.n_provisional)} после ${last.attempt} попыток, ложно подтверждённых ${intRu(last.confirmed_true_below)}` : ""} />
      </div>

      <h3 className="mt-8 text-base font-bold text-brand-night">Заявившие Junior: что решает правило</h3>
      <Table head={["", "До: подтверждён / отказ", "После: подтверждён / предварительно / отказ", "Механика до 06.10 без дотестирования, после"]}
        rows={[
          row("Заявили Junior", intRu(b.n_claimed_junior), intRu(a.n_claimed_junior), intRu(leg.after?.n_claimed_junior)),
          row("Из них истинный уровень ниже порога", intRu(b.n_true_below), intRu(a.n_true_below), intRu(leg.after?.n_true_below)),
          row("Подтверждён", `${intRu(b.confirmed)} (${pct(b.share?.confirmed)})`, `${intRu(a.confirmed)} (${pct(a.share?.confirmed)})`, `${intRu(leg.after?.confirmed)} (${pct(leg.after?.share?.confirmed)})`),
          row("Предварительно", "—", `${intRu(a.provisional)} (${pct(a.share?.provisional)})`, `${intRu(leg.after?.provisional)} (${pct(leg.after?.share?.provisional)})`),
          row("Отказ, категории нет", `${intRu(b.rejected)} (${pct(b.share?.rejected)})`, `${intRu(a.rejected)} (${pct(a.share?.rejected)})`, `${intRu(leg.after?.rejected)} (${pct(leg.after?.share?.rejected)})`),
          row("Ложные подтверждения (уровень ниже порога, подтверждён)", `${intRu(b.false_confirmed)} (${pct(b.false_confirmed_share)})`, `${intRu(a.false_confirmed)} (${pct(a.false_confirmed_share)})`, `${intRu(leg.after?.false_confirmed)} (${pct(leg.after?.false_confirmed_share)})`),
          row("Ложные предварительные (уровень ниже порога, предварительно)", "—", `${intRu(a.false_provisional)} (${pct(a.false_provisional_share)} предварительных)`, `${intRu(leg.after?.false_provisional)} (${pct(leg.after?.false_provisional_share)})`),
          row("Ложные отказы (уровень не ниже порога, категории нет)", `${intRu(b.false_rejected)} (${pct(b.false_rejected_share)})`, `${intRu(a.false_rejected)} (${pct(a.false_rejected_share)})`, `${intRu(leg.after?.false_rejected)} (${pct(leg.after?.false_rejected_share)})`),
        ]} />
      <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">
        Подтверждённые не меняются: «предварительно» берётся только из прежних отказов. Цена — часть предварительных действительно ниже порога; работодатель видит это как вероятность, в подборке они стоят ниже подтверждённых.
        Доли ошибок — от соответствующей группы по истинному уровню (ниже порога / не ниже).
      </p>

      {app.p_bands?.length ? (
        <div id="provisional-bands">
          <h3 className="mt-8 text-base font-bold text-brand-night">Как читать «предварительно»: полосы вероятности</h3>
          {r.how_to_read && <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">{r.how_to_read}</p>}
          <Table head={["P(θ ≥ порога Junior)", "Предварительных", "Из них истинный уровень ниже порога"]}
            rows={app.p_bands.map((x: any) => [`${n2(x.p_from)} – ${n2(x.p_to)}`, intRu(x.n), x.n ? `${intRu(x.true_below)} (${pct(x.true_below_share)})` : "—"])} />
        </div>
      ) : null}

      {c.attempts?.length ? (
        <>
          <h3 className="mt-8 text-base font-bold text-brand-night">Дотестирование предварительных ({intRu(c.n_provisional)} кандидатов, до {r.rule?.confirm_attempts} попыток по {r.rule?.confirm_ext_items} коротких заданий)</h3>
          <Table head={["Попытка", "Подтвердили Junior", "Из них с истинным уровнем ниже порога", "Остаются предварительными", "Из них ниже порога", "Новых заданий в среднем"]}
            rows={c.attempts.map((x: any) => [String(x.attempt), `${intRu(x.confirmed_total)} (${pct(x.confirmed_total / Math.max(c.n_provisional, 1))})`, intRu(x.confirmed_true_below), `${intRu(x.still_provisional)} (${pct(x.still_provisional / Math.max(c.n_provisional, 1))})`, intRu(x.still_provisional_true_below), n1(x.mean_new_items)])} />
          <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">
            Как в продукте: ответы прошлой сессии переносятся в θ, добавляются только короткие задания у порога Junior из ещё не показанных семейств. Доказанное «ниже» статус не снимает — решение владельца, поэтому отказов после дотестирования нет: статус либо подтверждается, либо остаётся предварительным с обновлённой вероятностью.
          </p>
        </>
      ) : null}

      <details className="mt-6 rounded-2xl bg-white p-5 text-sm ring-1 ring-brand-night/10">
        <summary className="cursor-pointer font-semibold text-brand-night">По направлениям и воспроизведение</summary>
        <div className="mt-3">
          <Table head={["Направление", "Заявили Junior", "Предварительных", "Ложных предварительных", "Ложные отказы до → после", "После дотестирования предварительных"]}
            rows={dirs.map(([d, v]) => { const p = v.policies?.app ?? {}; const l = p.confirm?.attempts?.[p.confirm.attempts.length - 1]; return [DIRECTIONS[d] ?? d, intRu(p.after?.n_claimed_junior), `${intRu(p.after?.provisional)} (${pct(p.after?.share?.provisional)})`, `${intRu(p.after?.false_provisional)} (${pct(p.after?.false_provisional_share)})`, `${intRu(p.before?.false_rejected)} → ${intRu(p.after?.false_rejected)}`, l ? `${intRu(l.still_provisional)} из ${intRu(p.confirm?.n_provisional)}` : "—"]; })} />
        </div>
        <p className="mt-3 text-brand-ink/70">
          Пересчёт: <code className="rounded bg-[#F3F2FB] px-1.5 py-0.5">make stability</code> ({intRu(r.seconds)} с), seed {r.seed}{r.signature ? <>, конфигурация <code>{r.signature.config_hash}</code>, коммит <code>{r.signature.commit}</code></> : null}; отчёт построен {r.generated_at?.slice(0, 10).split("-").reverse().join(".")}. Данные: backend/app/modules/validation/data/junior_stability.json.
        </p>
      </details>
    </>
  );
}

function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-2xl bg-white p-4 ring-1 ring-brand-night/10">
      <div className="text-xs font-medium uppercase tracking-[0.06em] text-brand-ink/60">{label}</div>
      <div className="mt-1 text-2xl font-extrabold tabular-nums text-brand-night">{value}</div>
      {hint && <div className="mt-1 text-xs text-brand-ink/65">{hint}</div>}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h, i) => <th key={i} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-brand-night/5">
              {r.map((c, j) => <td key={j} className={`px-3 py-2 tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
