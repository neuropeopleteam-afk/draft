// Профиль компании для кандидата: сведения, индекс доверия с причинами, открытые вакансии.
import { Link, useParams } from "react-router-dom";
import { Alert, Loading, catTitle, range, useApi } from "../components/ui";
import { TrustPanel, type Trust } from "./Trust";

export function CompanyPublic() {
  const { id } = useParams();
  const { data, loading, error } = useApi<any>(`/companies/${id}`, [id]);
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  const c = data;
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Профиль компании</p>
        <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-brand-night">{c.name}</h1>
        <p className="mt-1 text-sm text-brand-ink/65">{[c.industry, c.city, c.website].filter(Boolean).join(" · ")}{c.inn ? ` · ИНН ${c.inn}` : ""}</p>
      </div>
      {c.description && <p className="whitespace-pre-line text-brand-ink/80">{c.description}</p>}
      <TrustPanel t={data.trust as Trust} />
      <section className="space-y-3">
        <h2 className="font-bold text-brand-night">Открытые вакансии</h2>
        {!data.vacancies?.length ? <p className="text-sm text-brand-ink/65">Сейчас нет опубликованных вакансий. Компания может пригласить вас напрямую.</p> : (
          <ul className="space-y-2">
            {data.vacancies.map((v: any) => (
              <li key={v.id} className="card flex flex-wrap items-center justify-between gap-3">
                <div><p className="font-semibold text-brand-night">{v.title}</p><p className="text-sm text-brand-ink/65">{v.category_id ? `${catTitle(v.category_id)} · ` : ""}{range(v.salary_from, v.salary_to)}</p></div>
                <Link to="/candidate/vacancies" className="btn-ghost">К вакансиям</Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
