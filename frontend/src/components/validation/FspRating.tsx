import { Alert, Loading, num, signed, useApi } from "../ui";

export function FspRatingValidation() {
  const { data, error, loading } = useApi<any>("/validation/fsp-rating");
  if (loading) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  if (!data || data.missing) return null;
  const titles: Record<string, string> = {"ndcg@10": "nDCG@10", "ndcg@5": "nDCG@5", "p@10": "precision@10", "mrr": "MRR"};
  return <section className="mt-6 space-y-3" aria-labelledby="fsp-regression-title">
    <h3 id="fsp-regression-title" className="font-bold text-brand-night">Рейтинг ФСП: проверка до и после</h3>
    <p className="text-sm text-brand-ink/70">Тот же мир: {num(data.needs, 0)} потребностей × {num(data.candidates, 0)} кандидатов; seed {num(data.seed, 0)}. Истина и веса продукта не менялись.</p>
    <div className="overflow-x-auto rounded-xl border border-brand-night/10">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Метрики старой и новой формулы ФСП и парный 95-процентный доверительный интервал разницы</caption>
        <thead className="bg-[#F3F2FB]"><tr>{["Метрика", "До", "После", "Разница", "95 % ДИ разницы"].map(t => <th key={t} className="whitespace-nowrap p-3 font-semibold">{t}</th>)}</tr></thead>
        <tbody>{Object.entries(titles).map(([key, title]) => {const v = data.metrics[key]; return <tr key={key} className="border-t border-brand-night/10"><th className="p-3 font-medium">{title}</th><td className="p-3">{num(v.before, 4)}</td><td className="p-3">{num(v.after, 4)}</td><td className="p-3">{signed(v.delta, 4)}</td><td className="whitespace-nowrap p-3">{signed(v.paired_ci95[0], 4)} … {signed(v.paired_ci95[1], 4)}</td></tr>;})}</tbody>
      </table>
    </div>
    <p className="text-xs leading-relaxed text-brand-ink/65">Разница мала, доверительный интервал включает ноль. Численная потеря не скрыта: отсутствие статистически различимой потери не доказывает абсолютную неухудшаемость. Это синтетический набор, не проверка реального рынка. Пересчёт: tools/fsp_rating_regression.py.</p>
  </section>;
}
