import { Alert, Loading, num, pct, useApi } from "../ui";
import { ScrollX } from "../A11y";

/** Блок /validation: частичный балл 0–4 у развёрнутых ответов — «0/1» против «0–4» на одних и тех же модельных
 * кандидатах (backend: app/modules/validation/partial_credit_sim.py → data/partial_credit_sim.json; флаг
 * ASSESSMENT_PARTIAL_CREDIT_ENABLED). Согласие оценщика 0–4 — по сохранённым ответам набора оценщика. */

const ARM: Record<string, string> = { bin: "0/1", frac: "доля 0..1 (сейчас)", gpcm: "0–4, GPCM", gpcm_est: "0–4, GPCM только в оценке" };
const WORLD: Record<string, string> = { base: "основной", narrow: "пессимистичный", clean: "без шума оценщика" };
const pp = (v?: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${num(v * 100, 1)}\u00A0п.\u00A0п.`);
const ci = (c?: number[] | null) => (c ? ` [${pp(c[0])}; ${pp(c[1])}]` : "");

export default function PartialCredit() {
  const { data: r, error, loading } = useApi<any>("/validation/partial-credit", []);
  return (
    <section id="partial-credit" className="mt-12 scroll-mt-20" aria-labelledby="partial-credit-t">
      <h2 id="partial-credit-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Частичный балл 0–4 у развёрнутых ответов</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Симуляция ещё не посчитана: make partial-credit-sim.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const g = r.grader ?? {};
  const ag = g.agreement?.on_v3_skeptic ?? g.agreement?.off_v2 ?? {};
  const rows: any[] = r.rows ?? [];
  const main = rows.filter((x) => x.length === "adaptive");
  const fixed = rows.filter((x) => x.length === "fixed");
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Развёрнутый ответ оценивается по пунктам рубрики; балл 0–4 = округлённая взвешенная оценка × 4 — тот же вызов оценщика, без новых запросов. С флагом балл входит в оценку уровня по модели частичного балла (GPCM): «3 из 4» говорит о способности больше, чем «засчитано», а «1 из 4» — больше, чем «не засчитано». Без флага — как сейчас: доля 0..1 уже входит в оценку по 2PL. Ниже — одни и те же модельные кандидаты, одна длина теста; меняется только учёт развёрнутых ответов.
      </p>
      <div className="mt-3"><Alert kind="info"><b>{r.enabled ? "Флаг включён на этом стенде. " : "На стенде флаг выключен. "}</b>Синтетика: кандидаты и ответы — модель, не люди. В сессии не больше трёх развёрнутых ответов, поэтому прирост ограничен ими.</Alert></div>
      {Array.isArray(r.conclusions) && r.conclusions.length > 0 && (
        <ul className="mt-3 max-w-4xl list-disc space-y-1 pl-5 text-sm leading-relaxed text-brand-ink/80">
          {r.conclusions.map((c: string, i: number) => <li key={i}>{c}</li>)}
        </ul>
      )}
      {ag.n ? (
        <p className="mt-3 max-w-4xl text-sm text-brand-ink/75">
          Оценщик ({g.grader}) против эталона ({g.reference}) на {ag.n} честных ответах набора: 0–4 — κw {num(ag.kappa_w_0_4, 3)}, точно {pct(ag.exact_0_4, 1)}, ±1 балл {pct(ag.within1_0_4, 1)}; «0/1» — согласие {pct(ag.agree_0_1, 1)}, κ {num(ag.kappa_0_1, 3)}. Промежуточные баллы 1–3 у эталона — {pct(g.intermediate_share_reference, 1)} ответов. Эта матрица ошибок оценщика — шум в симуляции.
        </p>
      ) : null}
      <ScrollX label="Частичный балл: «0/1» против «0–4»" className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead><tr className="border-b border-brand-night/10 text-xs uppercase tracking-wide text-brand-lavender">
            <th className="py-2 pr-3">Мир</th><th className="py-2 pr-3">Порог P</th><th className="py-2 pr-3">Учёт ответа</th>
            <th className="py-2 pr-3">Точно</th><th className="py-2 pr-3">Выше</th><th className="py-2 pr-3">Повтор совпал</th>
            <th className="py-2 pr-3">κw повтора</th><th className="py-2 pr-3">SE</th><th className="py-2 pr-3">RMSE θ̂</th><th className="py-2 pr-3">Минут</th>
            <th className="py-2 pr-3">Точно: разница с «сейчас»</th>
          </tr></thead>
          <tbody>
            {main.map((x) => (
              <tr key={`${x.world}-${x.confirm}-${x.arm}`} className="border-b border-brand-night/5 align-top">
                <td className="py-2 pr-3 text-brand-ink/80">{WORLD[x.world] ?? x.world}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{num(x.confirm, 1)}</td>
                <td className="py-2 pr-3 font-medium text-brand-night">{ARM[x.arm] ?? x.arm}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{pct(x.exact, 1)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{pct(x.over, 1)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{pct(x.retest_exact, 1)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{num(x.retest_kappa_w, 3)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{num(x.se_first_mean, 3)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{x.rmse_theta_first == null ? "—" : num(x.rmse_theta_first, 3)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{num(x.minutes_per_path, 1)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{x.diff_vs_frac ? <>{pp(x.diff_vs_frac.exact)}<span className="text-xs text-brand-ink/60">{ci(x.diff_vs_frac.exact_ci)}</span></> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      {fixed.length > 0 && (
        <p className="mt-3 max-w-4xl text-sm text-brand-ink/75">
          Строго одна длина (16 заданий, без досрочной остановки): {fixed.map((x) => `${WORLD[x.world] ?? x.world}, ${ARM[x.arm] ?? x.arm} — точно ${pct(x.exact, 1)}, повтор ${pct(x.retest_exact, 1)}, SE ${num(x.se_first_mean, 3)}`).join("; ")}.
        </p>
      )}
      <p className="mt-2 text-xs text-brand-ink/65">
        {r.worlds?.base?.ru}; пессимистичный мир — {r.worlds?.narrow?.ru}. {r.caveat} Мир: {r.signature?.world}; seed {r.signature?.seed}; коммит {r.signature?.commit}. Данные: data/partial_credit_sim.json, docs/validation/PARTIAL_CREDIT.md; пересчёт — make partial-credit-sim.
      </p>
    </>
  );
}
