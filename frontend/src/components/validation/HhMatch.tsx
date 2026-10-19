import { Alert, Loading, useApi } from "../ui";
import { ScrollX } from "../A11y";
import { useMeta } from "../../lib/meta";

/** Блок /validation (Я12б): подбор на реальных вакансиях hh.ru — тексты реальные, кандидаты модельные; покрытие
 * требований, доля потребностей с подтверждёнными кандидатами, ошибки разбора; спрос по направлениям (число
 * вакансий на дату). Backend: tools/realdata/hh_plus.py match / demand → /api/validation/hh-match. При HH_ENABLED. */

interface Share { k: number; n: number; share: number | null }
const pct = (x?: Share | null) => (!x || x.share == null ? "—" : `${(x.share * 100).toFixed(1).replace(".", ",")}\u00A0% (${x.k} из ${x.n})`);
const mean = (x?: { mean: number | null } | null) => (!x || x.mean == null ? "—" : `${(x.mean * 100).toFixed(1).replace(".", ",")}\u00A0%`);
const d10 = (v?: string | null) => (v ? new Date(v).toLocaleDateString("ru-RU") : "—");
const num = (v: number) => v.toLocaleString("ru-RU");
const ROWS: [string, string][] = [
  ["direction_ok", "Направление разобрано верно (роль hh.ru)"], ["grade_ok", "Грейд разобран верно (слово в названии)"],
  ["key_skills_recall", "«Ключевые навыки» hh.ru найдены разбором"], ["with_required", "В потребности есть обязательные навыки"],
  ["confirmed_any", "Нашлись кандидаты с подтверждённым тестом грейдом"], ["confirmed_right_direction", "… в направлении вакансии"],
  ["confirmed_exact", "… в точной категории потребности"], ["req_full_top5", "В первой пятёрке есть кандидат со всеми обязательными"],
  ["req_full_top5_confirmed", "… и с подтверждённым грейдом"],
];
const th = "px-3 py-2.5 font-semibold";
const td = "px-3 py-2 tabular-nums text-brand-ink/80";

export default function HhMatch() {
  const on = useMeta()?.hh?.enabled ?? false;
  const { data: r, error, loading } = useApi<any>(on ? "/validation/hh-match" : null, [on]);
  if (!on) return null;
  return (
    <section id="hh-match" className="mt-12 scroll-mt-20" aria-labelledby="hh-match-t">
      <h2 id="hh-match-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Подбор на реальных вакансиях hh.ru</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Замер ещё не посчитан: tools/realdata/hh_plus.py match.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const o = r.overall ?? {}, k = r.catalog_only ?? {};
  const dirs: [string, any][] = Object.entries(r.directions ?? {});
  const dem: [string, any][] = Object.entries(r.demand?.directions ?? {}).sort((a: any, b: any) => b[1].russia - a[1].russia) as any;
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        <b data-testid="hh-match-signature">Тексты — реальные вакансии hh.ru, кандидаты — модельные (модель, не люди).</b>{" "}
        {r.n} вакансий девяти направлений каталога (корпус от {d10(r.corpus_collected_at)}, включая 4 новых направления) прошли наш разбор
        потребности (правила, без модели) и подборку на демо-пуле из 500 модельных кандидатов. Метки — из полей, которые работодатель
        заполнил на hh.ru (роль, слово грейда в названии, «Ключевые навыки»), разбору они не даются. В репозитории — номера и метки, без текстов.
      </p>
      <p className="mt-1 text-xs text-brand-ink/65">Прогон {d10(r.generated_at)} · код {r.code_commit} · алгоритм {r.algorithm} · недоступно: {r.n_missing ?? 0}</p>
      <div className="mt-4">
        <ScrollX label="Подбор на вакансиях hh.ru: итог" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
              <tr><th scope="col" className={th}>Показатель</th><th scope="col" className={th}>Направления каталога</th><th scope="col" className={th}>Все 9 направлений</th></tr>
            </thead>
            <tbody>
              {ROWS.map(([key, t]) => <tr key={key} className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">{t}</td><td className={td}>{pct(k[key])}</td><td className={td}>{pct(o[key])}</td></tr>)}
              <tr className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">Покрытие обязательных навыков у лучшего из пяти (T1, среднее)</td><td className={td}>{mean(k.req_coverage_best_top5)}</td><td className={td}>{mean(o.req_coverage_best_top5)}</td></tr>
              {k.req_coverage_mean_top5 && <tr className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">… в среднем по первой пятёрке</td><td className={td}>{mean(k.req_coverage_mean_top5)}</td><td className={td}>{mean(o.req_coverage_mean_top5)}</td></tr>}
              {k.grade_above_off && <tr className="border-t border-brand-night/5" data-testid="hh-match-before"><td className="px-3 py-2 font-medium text-brand-night">До добора уровнем выше (match-v1.2): лучший из пяти / в среднем по пятёрке</td><td className={td}>{mean(k.grade_above_off.req_coverage_best_top5)} / {mean(k.grade_above_off.req_coverage_mean_top5)}</td><td className={td}>{mean(o.grade_above_off?.req_coverage_best_top5)} / {mean(o.grade_above_off?.req_coverage_mean_top5)}</td></tr>}
              {k.grade_above_applied && <tr className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">Добор уровнем выше сработал (в точной категории меньше 30)</td><td className={td}>{pct(k.grade_above_applied)}</td><td className={td}>{pct(o.grade_above_applied)}</td></tr>}
            </tbody>
          </table>
        </ScrollX>
      </div>
      <div className="mt-4">
        <ScrollX label="Подбор на вакансиях hh.ru по направлениям" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
              <tr><th scope="col" className={th}>Направление</th><th scope="col" className={th}>n</th><th scope="col" className={th}>Направление верно</th><th scope="col" className={th}>Подтверждённые кандидаты в направлении</th><th scope="col" className={th}>Покрытие (лучший из 5)</th></tr>
            </thead>
            <tbody>
              {dirs.map(([d, x]) => (
                <tr key={d} className="border-t border-brand-night/5">
                  <td className="px-3 py-2 font-medium text-brand-night">{x.title}{x.in_catalog ? "" : " (новое)"}</td>
                  <td className={td}>{x.n}</td>
                  <td className={td}>{x.in_catalog ? pct(x.direction_ok) : `нет в каталоге → ${Object.keys(x.parsed_direction ?? {})[0] ?? "—"}`}</td>
                  <td className={td}>{pct(x.confirmed_right_direction)}</td>
                  <td className={td}>{mean(x.req_coverage_best_top5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollX>
      </div>
      <p className="mt-2 text-xs text-brand-ink/65">
        «Подтверждённые» — модельные кандидаты, чей грейд подтверждён тестом. Покрытие — доля обязательных навыков потребности, подтверждённых тестом (T1),
        у лучшего из первых пяти.{r.grade_above ? " Добор уровнем выше (match-v1.3): если в точной категории меньше 30 кандидатов, подборка добавляет категорию на ступень выше; первые 2 места — лучшие точного уровня, дальше кандидат уровнем выше стоит выше точного, только если покрывает больше обязательного. На синтетике со скрытой истиной P@5, nDCG и MRR не ниже прежних (docs/validation/grade_above.json)." : ""} Направления, которых пока нет в каталоге, разбор относит к ближайшему — это ошибка, которую закрывает расширение каталога.
        Ошибки разбора по полям: {Object.entries<number>(r.errors_by_field ?? {}).map(([f, n]) => `${f} — ${n}`).join(", ") || "—"}. Подробно — docs/validation/HH_MATCH.md.
      </p>
      {r.w1?.rows?.length > 0 && (
        <div className="mt-6 rounded-2xl bg-white p-4 ring-1 ring-brand-night/10" data-testid="hh-match-w1">
          <h3 className="font-bold text-brand-night">Что изменилось: по шагам</h3>
          <p className="mt-1 text-xs leading-relaxed text-brand-ink/70">{r.w1.summary}</p>
          <ScrollX label="Шаги изменений подбора на вакансиях hh.ru" className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-xs text-brand-ink/70"><tr><th scope="col" className={th}>Шаг</th><th scope="col" className={th}>Подтверждённый в направлении вакансии</th><th scope="col" className={th}>Покрытие у лучшего из 5</th></tr></thead>
              <tbody>
                {r.w1.rows.map((x: any) => <tr key={x.title} className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">{x.title}</td><td className={td}>{pct(x.confirmed_right_direction)}</td><td className={td}>{mean(x.req_coverage_best_top5)}</td></tr>)}
              </tbody>
            </table>
          </ScrollX>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-brand-ink/70">{(r.w1.caveats ?? []).map((c: string) => <li key={c}>{c}</li>)}</ul>
        </div>
      )}
      {dem.length > 0 && (
        <>
          <h3 className="mt-6 font-bold text-brand-night">Спрос по направлениям на hh.ru</h3>
          <p className="mt-1 text-xs text-brand-ink/65">Число открытых вакансий в поиске hh.ru на {d10(r.demand?.as_of)}: роль + слова направления в названии. Объявления работодателей, не число рабочих мест; на платформе сами вакансии не показываются.</p>
          <div className="mt-2">
            <ScrollX label="Спрос по направлениям на hh.ru" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
              <table className="w-full min-w-[32rem] text-left text-sm">
                <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
                  <tr><th scope="col" className={th}>Направление</th><th scope="col" className={th}>Россия</th><th scope="col" className={th}>Москва</th><th scope="col" className={th}>Санкт-Петербург</th><th scope="col" className={th}>Без опыта</th></tr>
                </thead>
                <tbody>
                  {dem.map(([d, x]) => <tr key={d} className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">{x.title}{x.new ? " (новое)" : ""}</td><td className={td}>{num(x.russia)}</td><td className={td}>{num(x.moscow)}</td><td className={td}>{num(x.spb)}</td><td className={td}>{num(x.no_experience)}</td></tr>)}
                </tbody>
              </table>
            </ScrollX>
          </div>
        </>
      )}
    </>
  );
}
