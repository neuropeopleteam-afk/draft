import { Alert, Loading, NB, num, useApi } from "../ui";
import { SignatureLine } from "./Headline";

/** Блок /validation: абляции подбора на бенчмарке со скрытой истиной (backend: matching_bench.ablations, make bench). */

const cell = (c?: { mean: number; lo: number; hi: number }, sign = false) => c
  ? <>{sign && c.mean > 0 ? "+" : ""}{num(c.mean, 3)}<span className="block text-xs text-brand-ink/60">{num(c.lo, 3)} … {num(c.hi, 3)}</span></>
  : "—";

export default function Ablations() {
  const { data: b, error, loading } = useApi<any>("/validation/matching-bench", []);
  if (loading) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  if (!b || b.missing) return null;
  const rows: any[] = b.ablations ?? [];
  return (
    <section id="ablations" className="mt-12 scroll-mt-20" aria-labelledby="ablations-t">
      <h2 id="ablations-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Абляции: что даёт каждая часть формулы подбора</h2>
      {!rows.length ? <div className="mt-4"><Alert kind="info">Абляции появятся после пересчёта: make bench.</Alert></div> : <>
        <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">Тот же мир, та же скрытая истина, тот же разбор потребностей; из формулы убирается одна часть. Δ — «полная формула − вариант», парный бутстреп по потребностям, 95{NB}% ДИ. Положительная Δ — часть помогает; интервал через ноль — вклад не различим.</p>
        <div className="mt-4 overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <caption className="sr-only">Абляции подбора: precision@5 и nDCG@10 с доверительными интервалами</caption>
            <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
              <tr>{["Вариант", "precision@5", "nDCG@10", "Δ precision@5", "Δ nDCG@10"].map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody>{rows.map((a) => {
              const meta = b.methods?.[a.method] ?? {};
              return <tr key={a.method} className={`border-t border-brand-night/5 ${a.method === "platform" ? "bg-brand-blush/15 font-semibold" : ""}`}>
                <th scope="row" className="px-3 py-2 align-top font-medium text-brand-night"><span title={meta.text}>{meta.title ?? a.method}</span>{a.method !== "platform" && <span className="block text-xs font-normal text-brand-ink/60">{meta.text}</span>}</th>
                <td className="px-3 py-2 align-top tabular-nums">{cell(a["p@5"])}</td>
                <td className="px-3 py-2 align-top tabular-nums">{cell(a["ndcg@10"])}</td>
                <td className="px-3 py-2 align-top tabular-nums">{cell(a["diff_p@5"], true)}</td>
                <td className="px-3 py-2 align-top tabular-nums">{cell(a["diff_ndcg@10"], true)}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Тест работает в подборе в основном через ярус грейда и подтверждённые навыки: без яруса и без теста подбор теряет больше всего, а θ внутри яруса добавляет немного. Мир бенчмарка синтетический (истина порождена моделью мира) — это проверка механики, не рынка.</p>
        <SignatureLine s={b.signature ?? { world: `бенчмарк подбора: ${b.world?.n_needs} × ${b.world?.n_candidates}`, seed: b.seeds?.world, config_hash: b.config_hash, commit: "—", command: b.command }} className="mt-2" />
      </>}
    </section>
  );
}
