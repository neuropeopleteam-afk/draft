// Кабинет ФСП (роль fsp_analyst): обезличенная аналитика платформы — только агрегаты, группы меньше 5 скрыты.
import { useState } from "react";
import { Link, Outlet, useOutletContext } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, GRADES, Loading, Seg, Stat, dt, errText, range, useApi } from "../../components/ui";
import { apiDownload } from "../../lib/api";
import { BarList, Donut, Funnel, Heatmap, Legend, PairBars, RangeChart, StackBar, fk, fpct, ftr, fx, type Stage } from "../charts";
import { MODE_SHORT, Phase } from "../shared";

type Rep = any;
interface Ctx { rep: Rep | null; loading: boolean; error: string | null; days: string; setDays: (d: string) => void }

const PERIODS = [{ id: "all", title: "Всё время" }, { id: "180", title: "180 дней" }, { id: "90", title: "90 дней" }, { id: "30", title: "30 дней" }];
const KEY = "fsp_cabinet_days";
const DIRS = Object.entries(DIRECTIONS).map(([id, title]) => ({ id, title: id === "security" ? "ИБ" : title }));
const GRS = Object.entries(GRADES).map(([id, title]) => ({ id, title }));
const q = (days: string) => (days === "all" ? "" : `?days=${days}`);
/** Отклонение в процентах со знаком: «+4,2 %», «−10 %». */
const sgn = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} %`;

/** Обёртка разделов: один запрос /fsp-cabinet/report на период, общий для всех экранов кабинета. */
export function FspReportLayout() {
  const [days, setDaysS] = useState(() => localStorage.getItem(KEY) ?? "all");
  const { data, loading, error } = useApi<Rep>(`/fsp-cabinet/report${q(days)}`, [days]);
  const setDays = (d: string) => { localStorage.setItem(KEY, d); setDaysS(d); };
  return <Outlet context={{ rep: data, loading, error, days, setDays } satisfies Ctx} />;
}

const useRep = () => useOutletContext<Ctx>();

function Head({ title, subtitle, csv }: { title: string; subtitle: string; csv?: { id: string; title: string }[] }) {
  const { days, setDays, loading, rep } = useRep();
  const [err, setErr] = useState<string | null>(null);
  async function download(id: string) {
    setErr(null);
    try { await apiDownload(`/fsp-cabinet/export/${id}.csv${q(days)}`, `fsp_${id}.csv`); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="space-y-4">
      <PageTitle title={title} subtitle={subtitle} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="hidden sm:inline-flex"><Seg label="Период" value={days} onChange={setDays} options={PERIODS} /></span>
        <label className="flex items-center gap-2 text-sm sm:hidden">
          <span className="font-semibold text-brand-night">Период</span>
          <select className="input w-auto py-2" value={days} onChange={(e) => setDays(e.target.value)}>
            {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        </label>
        <span className="text-xs text-brand-ink/55" aria-live="polite">
          {loading ? "Обновляем…" : rep ? `Только агрегаты · группы меньше ${rep.k} человек скрыты` : ""}
        </span>
        {csv && (
          <span className="flex flex-wrap gap-2 sm:ml-auto">
            {csv.map((c) => <button key={c.id} className="btn-ghost px-3 py-1.5 text-xs" onClick={() => download(c.id)}>CSV: {c.title}</button>)}
          </span>
        )}
      </div>
      {err && <Alert>{err}</Alert>}
    </div>
  );
}

function Body({ children }: { children: (rep: Rep) => React.ReactNode }) {
  const { rep, error, loading } = useRep();
  if (error && !rep) return <Alert>{error}</Alert>;
  if (loading && !rep) return <Loading />;
  if (!rep) return null;
  return <>{children(rep)}</>;
}

function Card({ title, sub, children, more }: { title: string; sub?: string; children: React.ReactNode; more?: { to: string; label: string } }) {
  return (
    <section className="card min-w-0 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold text-brand-night">{title}</h2>
          {sub && <p className="mt-1 text-sm text-brand-ink/60">{sub}</p>}
        </div>
        {more && <Link to={more.to} className="text-sm font-semibold text-brand hover:text-brand-soft">{more.label} →</Link>}
      </div>
      {children}
    </section>
  );
}

function DemoNote({ rep }: { rep: Rep }) {
  if (!(rep.overview.demo_share >= 0.99)) return null;
  return (
    <Alert kind="info">
      Сейчас в данных только демо-компании и демо-кандидаты стенда: история приглашений для аналитики сгенерирована по модели
      поведения, кубки проведены по правилам платформы. На живых данных кабинет считает те же показатели по реальным офферам.
    </Alert>
  );
}

const dirSum = (rows: any[], key: string) => DIRS.map((d) => ({ ...d, v: rows.filter((r) => r.direction === d.id).reduce((s, r) => s + (r[key] ?? 0), 0) }));

// ------------------------------------------------------------------ обзор

export function FspOverview() {
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Кабинет ФСП" subtitle="Обезличенная аналитика платформы для федерации: чего ждут работодатели, как соревнования ФСП влияют на приглашения, какие зарплаты предлагают на деле." />
      <Body>{(rep) => {
        const o = rep.overview, fe = rep.fsp_effect;
        const [nofsp, fsp] = fe.groups;
        const top = [...rep.demand.categories].sort((a: any, b: any) => b.invitations - a.invitations)[0];
        const sal = rep.salaries.categories.filter((r: any) => r.delta_vs_market_pct != null);
        const avgDelta = sal.length ? sal.reduce((s: number, r: any) => s + r.delta_vs_market_pct, 0) / sal.length : null;
        const byDir = dirSum(rep.demand.categories, "invitations");
        const cupF: Stage[] = rep.funnel.cups;
        return (
          <>
            <DemoNote rep={rep} />
            <div className="grid grid-cols-2 gap-3 md:gap-5 lg:grid-cols-4">
              <Stat label="Кандидаты" value={fk(o.candidates)} hint={`с категорией · с ФСП ${fk(o.candidates_fsp)} (${fpct(o.fsp_share)})`} />
              <Stat label="Работодатели" value={o.companies_active} hint={`активных компаний · потребностей ${o.needs}`} />
              <Stat label="Приглашения" value={o.invitations} hint={`получили ${fk(o.invited_candidates)} кандидатов`} />
              <Stat label="Кубки" value={o.cups} hint={`участвовали ${fk(o.cup_participants)} кандидатов`} />
            </div>
            <section className="card space-y-3">
              <h2 className="text-lg font-bold text-brand-night">Главное за период</h2>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-brand-ink/85 marker:text-brand">
                {fsp.lift_vs_no_fsp != null && (
                  <li>Кандидатов с подтверждёнными достижениями ФСП приглашают в <b>{fsp.invite_rate != null && nofsp.invite_rate ? (fsp.invite_rate / nofsp.invite_rate).toLocaleString("ru-RU", { maximumFractionDigits: 2 }) : "—"} раза</b> чаще ({fpct(fsp.invite_rate)} против {fpct(nofsp.invite_rate)}); с поправкой на категорию — {fx(fsp.adjusted_ratio)} к ожидаемому. Связь наблюдательная: рейтинг уже учитывает ФСП.</li>
                )}
                {top && <li>Самый высокий спрос — <b>{top.title}</b>: {top.invitations} приглашений от {top.companies} компаний{top.invite_rate != null ? `, приглашены ${fpct(top.invite_rate)} кандидатов категории` : ""}.</li>}
                {avgDelta != null && <li>Середина вилки в офферах в среднем <b>{Math.abs(avgDelta).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} % {avgDelta < 0 ? "ниже" : "выше"}</b> рыночной медианы категории (по {sal.length} категориям, где офферов достаточно).</li>}
                {cupF[2]?.count != null && <li>Кубки работодателей: из {fk(cupF[0].count)} участий место получили {fk(cupF[1].count)}, приглашения — {fk(cupF[2].count)}, приняли — {fk(cupF[3].count)}.</li>}
              </ul>
            </section>
            <div className="grid gap-5 lg:grid-cols-2">
              <Card title="ФСП и приглашения" sub="Доля кандидатов, получивших приглашение" more={{ to: "effect", label: "Подробнее" }}>
                <div className="grid grid-cols-3 gap-2">
                  <Donut value={fsp.invite_rate} label="с достижениями ФСП (T2)" tone="night" />
                  <Donut value={nofsp.invite_rate} label="без истории ФСП (нейтрально)" tone="lavender" />
                  <Donut value={o.acceptance_rate} label="приглашений принято (из отвеченных)" tone="brand" />
                </div>
              </Card>
              <Card title="Спрос по направлениям" sub="Приглашения-офферы за период" more={{ to: "demand", label: "Категории и навыки" }}>
                <BarList rows={byDir.map((d) => ({ key: d.id, label: DIRECTIONS[d.id], value: d.v }))} labelWidth="11rem" />
              </Card>
              <Card title="Воронка кандидатов" sub="Категория → приглашение → принятие" more={{ to: "funnel", label: "Все воронки" }}>
                <Funnel stages={rep.funnel.all} />
              </Card>
              <Card title="Офферы против рынка" sub="Середина вилки и рыночная медиана, тыс. ₽" more={{ to: "salaries", label: "Зарплаты" }}>
                <BarList labelWidth="11rem" max={Math.max(1, ...sal.map((r: any) => Math.abs(r.delta_vs_market_pct)))}
                  rows={sal.slice(0, 8).map((r: any) => ({
                    key: r.category_id, label: r.title, value: Math.abs(r.delta_vs_market_pct), tone: r.delta_vs_market_pct < 0 ? "lavender" : "brand",
                    display: sgn(r.delta_vs_market_pct),
                    sub: `${ftr(r.mid_median)} против ${ftr(r.market_median)}`,
                  }))} />
              </Card>
            </div>
          </>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ спрос

const METRICS = [
  { id: "invitations", title: "Приглашения", fmt: (v: any) => fk(v) },
  { id: "needs", title: "Потребности", fmt: (v: any) => fk(v) },
  { id: "invite_rate", title: "Доля приглашённых", fmt: (v: any) => fpct(v) },
  { id: "supply", title: "Кандидаты", fmt: (v: any) => fk(v) },
] as const;

export function FspDemand() {
  const [metric, setMetric] = useState<(typeof METRICS)[number]["id"]>("invitations");
  const [allSkills, setAllSkills] = useState(false);
  const m = METRICS.find((x) => x.id === metric)!;
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Спрос работодателей" subtitle="Какие категории и навыки нужны компаниям: потребности, приглашения-офферы и предложение подтверждённых кандидатов."
        csv={[{ id: "demand", title: "категории" }, { id: "skills", title: "навыки" }]} />
      <Body>{(rep) => {
        const cats: any[] = rep.demand.categories;
        const get = (d: string, g: string) => cats.find((c) => c.direction === d && c.grade === g)?.[metric];
        const total = (x: any) => x.needs_required + x.needs_desired;
        const skillsAll: any[] = [...rep.demand.skills].sort((a, b) => total(b) - total(a) || b.needs_required - a.needs_required);
        const skills = allSkills ? skillsAll : skillsAll.slice(0, 12);
        const smax = Math.max(1, ...skills.map((s) => s.needs_required + s.needs_desired));
        const noGrade = Object.entries(rep.demand.needs_without_grade ?? {});
        return (
          <>
            <DemoNote rep={rep} />
            <Card title="Категории «направление · грейд»" sub="Выберите показатель. Пустая клетка с пунктиром — группа меньше 5 человек.">
              <Seg label="Показатель" value={metric} onChange={setMetric} options={METRICS.map(({ id, title }) => ({ id, title }))} />
              <Heatmap rows={DIRS} cols={GRS} cell={get} fmt={m.fmt} tone={metric === "needs" || metric === "invitations" ? "brand" : "night"} />
              {noGrade.length > 0 && <p className="text-xs text-brand-ink/55">Потребности без грейда: {noGrade.map(([d, n]) => `${DIRECTIONS[d] ?? d} — ${n}`).join(", ")}.</p>}
            </Card>
            <Card title="Навыки в потребностях" sub="Сколько потребностей требуют навык (обязательно и желательно) и как часто приглашают тех, кто подтвердил его тестом (T1).">
              <Legend items={[{ tone: "brand", label: "обязательно" }, { tone: "soft", label: "желательно" }]} />
              <ul className="space-y-3">
                {skills.map((s) => (
                  <li key={s.tag} className="grid gap-x-3 gap-y-1 sm:grid-cols-[11rem_minmax(0,1fr)_14rem] sm:items-center">
                    <span className="text-sm font-medium text-brand-ink/85">{s.title}</span>
                    <span className="flex items-center gap-2">
                      <StackBar max={smax} parts={[{ value: s.needs_required, tone: "brand", label: "обязательно" }, { value: s.needs_desired, tone: "soft", label: "желательно" }]} />
                      <span className="w-8 shrink-0 text-right text-sm font-semibold tabular-nums text-brand-night">{s.needs_required + s.needs_desired}</span>
                    </span>
                    <span className="text-xs text-brand-ink/60">
                      компаний {s.companies} · подтвердили {fk(s.supply_confirmed)} · приглашены {fpct(s.invite_rate_with_skill)}
                    </span>
                  </li>
                ))}
              </ul>
              {skillsAll.length > 12 && (
                <button className="text-sm font-semibold text-brand-plum hover:text-brand" onClick={() => setAllSkills(!allSkills)}>
                  {allSkills ? "Свернуть" : `Показать все навыки (${skillsAll.length})`}
                </button>
              )}
            </Card>
            <Card title="Таблица по категориям">
              <div className="-mx-6 overflow-x-auto px-6">
                <table className="w-full min-w-[46rem] text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-brand-ink/50">
                    <tr><th className="py-2 pr-3">Категория</th><th className="pr-3 text-right">Потребности</th><th className="pr-3 text-right">Компании</th><th className="pr-3 text-right">Приглашения</th><th className="pr-3 text-right">Кандидаты</th><th className="pr-3 text-right">Приглашены</th><th className="pr-3 text-right">Приняли</th><th className="text-right">Медиана рынка</th></tr>
                  </thead>
                  <tbody className="divide-y divide-brand-night/5 tabular-nums">
                    {cats.map((c) => (
                      <tr key={c.category_id}>
                        <td className="py-2 pr-3 font-medium text-brand-night">{c.title}</td>
                        <td className="pr-3 text-right">{c.needs}</td>
                        <td className="pr-3 text-right">{c.companies}</td>
                        <td className="pr-3 text-right">{c.invitations}</td>
                        <td className="pr-3 text-right">{fk(c.supply)}</td>
                        <td className="pr-3 text-right">{fk(c.invited_candidates)}{c.invite_rate != null && <span className="text-brand-ink/50"> · {fpct(c.invite_rate)}</span>}</td>
                        <td className="pr-3 text-right">{fk(c.accepted_candidates)}{c.accept_rate != null && <span className="text-brand-ink/50"> · {fpct(c.accept_rate)}</span>}</td>
                        <td className="text-right">{ftr(c.market_median)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ эффект ФСП

function groupRows(rows: any[]) {
  return rows.map((g) => ({
    key: g.key, label: g.title, value: g.invite_rate, muted: g.candidates === 0,
    display: g.invite_rate != null ? fpct(g.invite_rate) : g.candidates === 0 ? "нет" : "скрыто",
    sub: g.secondary_suppressed ? "скрыто, чтобы малую соседнюю группу нельзя было восстановить вычитанием"
      : g.candidates === 0 ? "нет кандидатов" : g.candidates == null ? "кандидатов меньше 5 — группу не раскрываем"
      : g.invite_rate == null ? `кандидатов ${g.candidates}, приглашённых меньше 5 — долю не раскрываем`
      : `кандидатов ${fk(g.candidates)} · приглашены ${fk(g.invited)} · ${fx(g.lift_vs_no_fsp)} к «без ФСП» · с поправкой на категорию ${fx(g.adjusted_ratio)}`,
  }));
}

export function FspEffect() {
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Эффект соревнований ФСП" subtitle="Какие дисциплины, разряды, результаты и уровни соревнований ФСП ведут к приглашениям. Учитываются только достижения, подтверждённые реестром (T2)."
        csv={[{ id: "fsp", title: "эффект ФСП" }]} />
      <Body>{(rep) => {
        const fe = rep.fsp_effect;
        const [nofsp, fsp] = fe.groups;
        const base = fe.base_invite_rate;
        const max = Math.max(0.01, ...[...fe.groups, ...fe.disciplines, ...fe.ranks, ...fe.results, ...fe.levels].map((g: any) => g.invite_rate ?? 0));
        const baseLabel = `Без истории ФСП: ${fpct(base)}`;
        return (
          <>
            <DemoNote rep={rep} />
            <div className="grid gap-3 sm:grid-cols-3 md:gap-5">
              <Stat label="С ФСП (T2)" value={fpct(fsp.invite_rate)} hint={`приглашены ${fk(fsp.invited)} из ${fk(fsp.candidates)}`} />
              <Stat label="Без истории ФСП" value={fpct(nofsp.invite_rate)} hint={`приглашены ${fk(nofsp.invited)} из ${fk(nofsp.candidates)} · без штрафа`} />
              <Stat label="Отношение" value={fx(fsp.lift_vs_no_fsp)} hint={`с поправкой на категорию ${fx(fsp.adjusted_ratio)} к ожидаемому`} />
            </div>
            <Card title="По направлениям" sub="Доля приглашённых среди кандидатов направления">
              <PairBars a={{ label: "с достижениями ФСП", tone: "night" }} b={{ label: "без истории ФСП", tone: "lavender" }}
                rows={fe.by_direction.map((d: any) => ({ key: d.direction, label: d.title, a: d.fsp.invite_rate, b: d.no_fsp.invite_rate,
                  aText: d.fsp.invite_rate == null ? (d.fsp.candidates === 0 ? "нет" : "< 5") : undefined,
                  bText: d.no_fsp.invite_rate == null ? (d.no_fsp.candidates === 0 ? "нет" : "< 5") : undefined }))} />
            </Card>
            <p className="flex items-center gap-2 text-xs text-brand-ink/60"><span className="h-3 border-l-2 border-dashed border-brand-night/50" aria-hidden /> Пунктир на графиках ниже — доля приглашённых без истории ФСП ({fpct(base)}).</p>
            <div className="grid gap-5 2xl:grid-cols-2">
              <Card title="Дисциплины ЕВСК" sub="Доля приглашённых среди кандидатов с достижением в дисциплине">
                <BarList rows={groupRows(fe.disciplines)} max={max} base={base} baseLabel={baseLabel} tone="night" labelWidth="12rem" />
              </Card>
              <Card title="Спортивный разряд" sub="По данным паспорта ФСП">
                <BarList rows={groupRows(fe.ranks)} max={max} base={base} baseLabel={baseLabel} tone="plum" labelWidth="9rem" />
              </Card>
              <Card title="Лучший результат" sub="Победа, призовое место, финал или участие">
                <BarList rows={groupRows(fe.results)} max={max} base={base} baseLabel={baseLabel} tone="brand" labelWidth="12rem" />
              </Card>
              <Card title="Уровень соревнований" sub="Самый высокий уровень, на котором есть достижение">
                <BarList rows={groupRows(fe.levels)} max={max} base={base} baseLabel={baseLabel} tone="soft" labelWidth="10rem" />
              </Card>
            </div>
            <Alert kind="info">
              Связь наблюдательная, а не причинная: рейтинг внутри категории уже учитывает достижения ФСП (их вес в рейтинге — 25 %), поэтому
              рядом с прямым отношением показан коэффициент с поправкой на категорию — приглашённые к ожидаемым при доле приглашённых
              в категории каждого кандидата. Кубки работодателей (мероприятия платформы, T1) здесь не учитываются — они в «Воронках».
            </Alert>
          </>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ зарплаты

export function FspSalaries() {
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Зарплаты из офферов" subtitle="Реальные вилки из приглашений-офферов (вилка «от–до» обязательна) против рыночного диапазона категории."
        csv={[{ id: "salaries", title: "зарплаты" }]} />
      <Body>{(rep) => {
        const s = rep.salaries;
        const rows: any[] = s.categories;
        return (
          <>
            <DemoNote rep={rep} />
            <Card title="Вилки по категориям" sub={`Ячейка раскрывается при ${s.rules.min_offers}+ офферах, ${s.rules.min_candidates}+ кандидатах и ${s.rules.min_companies}+ компаниях: вилку одной компании не восстановить.`}>
              <RangeChart rows={rows.map((r) => ({
                key: r.category_id, label: r.title, market: r.market_from && r.market_to ? [r.market_from, r.market_to] : null,
                marketMedian: r.market_median, offer: r.suppressed ? null : [r.from_median, r.to_median], mid: r.suppressed ? null : r.mid_median,
                note: r.suppressed ? `офферов ${fk(r.offers)} — скрыто (${r.reason})`
                  : `офферов ${r.offers} · середина ${ftr(r.mid_median)}${r.delta_vs_market_pct != null ? ` · к медиане рынка ${sgn(r.delta_vs_market_pct)}` : ""}`,
              }))} />
            </Card>
            <Card title="По направлениям" sub="Квартили нижней и верхней границы вилки">
              <div className="-mx-6 overflow-x-auto px-6">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-brand-ink/50">
                    <tr><th className="py-2 pr-3">Направление</th><th className="pr-3 text-right">Офферы</th><th className="pr-3 text-right">«От», p25</th><th className="pr-3 text-right">«От», медиана</th><th className="pr-3 text-right">«До», медиана</th><th className="pr-3 text-right">«До», p75</th><th className="text-right">Середина</th></tr>
                  </thead>
                  <tbody className="divide-y divide-brand-night/5 tabular-nums">
                    {s.directions.map((d: any) => (
                      <tr key={d.direction}>
                        <td className="py-2 pr-3 font-medium text-brand-night">{d.title}</td>
                        <td className="pr-3 text-right">{fk(d.offers)}</td>
                        {d.suppressed ? <td colSpan={5} className="text-right text-brand-ink/45">скрыто: {d.reason}</td> : (
                          <>
                            <td className="pr-3 text-right">{ftr(d.from_p25)}</td><td className="pr-3 text-right">{ftr(d.from_median)}</td>
                            <td className="pr-3 text-right">{ftr(d.to_median)}</td><td className="pr-3 text-right">{ftr(d.to_p75)}</td>
                            <td className="text-right font-semibold text-brand-night">{ftr(d.mid_median)}</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            {rows.some((r) => r.accepted_mid_median && r.declined_mid_median) && (
              <Card title="Принятые и отклонённые офферы" sub="Медиана середины вилки — где обе группы раскрываемы">
                <PairBars fmt={ftr} a={{ label: "приняты", tone: "night" }} b={{ label: "отклонены", tone: "lavender" }}
                  rows={rows.filter((r) => r.accepted_mid_median && r.declined_mid_median).map((r) => ({ key: r.category_id, label: r.title, a: r.accepted_mid_median, b: r.declined_mid_median }))} />
              </Card>
            )}
            <p className="text-xs text-brand-ink/55">Рынок — {rows.find((r) => r.market_source)?.market_source ?? "Хабр Карьера"}, p25–p75 по категории.</p>
          </>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ воронки

export function FspFunnel() {
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Воронки" subtitle="Соревнование → приглашение → принятие: участники соревнований ФСП, кандидаты без истории ФСП и участники кубков работодателей." />
      <Body>{(rep) => {
        const f = rep.funnel;
        const conv = (st: Stage[], i: number) => st[i]?.conversion;
        return (
          <>
            <DemoNote rep={rep} />
            <Card title="Кубки работодателей: соревнование → приглашение" sub="Кубок — ограниченное по времени соревнование в категории; лучшим уходят приглашения с вилкой кубка.">
              <Funnel stages={f.cups} tone="brand" />
            </Card>
            <div className="grid gap-5 lg:grid-cols-2">
              <Card title="С достижениями ФСП (T2)"><Funnel stages={f.fsp} tone="night" /></Card>
              <Card title="Без истории ФСП"><Funnel stages={f.no_fsp} tone="lavender" /></Card>
            </div>
            <Card title="Конверсии рядом" sub="Доля перешедших на следующий этап">
              <PairBars a={{ label: "с ФСП", tone: "night" }} b={{ label: "без ФСП", tone: "lavender" }}
                rows={[1, 2, 3].map((i) => ({ key: String(i), label: f.all[i].title, a: conv(f.fsp, i), b: conv(f.no_fsp, i) }))} />
            </Card>
            <Card title="Все кандидаты"><Funnel stages={f.all} tone="plum" /></Card>
            <p className="text-xs text-brand-ink/55">{f.note}</p>
          </>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ кубки

export function FspCups() {
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Кубки работодателей" subtitle="Кубок — публичное мероприятие платформы: компания и условия открыты, участники — только числом. Места записываются в паспорт ФСП (уровень «платформа», T1)." />
      <Body>{(rep) => {
        const cups: any[] = rep.cups;
        if (!cups.length) return <Alert kind="info">За выбранный период кубков не было.</Alert>;
        return (
          <div className="grid gap-4 lg:grid-cols-2">
            {cups.map((c) => (
              <article key={c.id} className="card space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{c.category_title} · {MODE_SHORT[c.mode] ?? c.mode}</p>
                    <h2 className="mt-1 text-lg font-bold text-brand-night">{c.title}</h2>
                    <p className="text-sm text-brand-ink/65">{c.company}</p>
                  </div>
                  <Phase p={c.phase} />
                </div>
                <p className="text-sm text-brand-ink/70">{dt(c.starts_at)} — {dt(c.ends_at)} · {range(c.salary_from, c.salary_to)} · приглашения топ-{c.invite_top_n}</p>
                <dl className="grid grid-cols-3 gap-2 text-center sm:grid-cols-5">
                  {[["Участники", c.participants], ["С местом", c.placed], ["Приглашены", c.invited], ["Приняли", c.accepted], ["В паспорте", c.passport_written]].map(([t, v]) => (
                    <div key={t as string} className="rounded-xl bg-[#F7F4FA] px-2 py-2">
                      <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-ink/50">{t}</dt>
                      <dd className="mt-0.5 text-base font-bold tabular-nums text-brand-night">{fk(v as number | null)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="text-xs text-brand-ink/55">
                  {c.score_median_pct != null ? `Медиана балла ${c.score_median_pct} %. ` : ""}
                  {c.passport_pending ? `Ждут связки с ФСП ID: ${fk(c.passport_pending)}.` : ""}
                </p>
              </article>
            ))}
          </div>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ методика

export function FspMethod() {
  return (
    <div className="max-w-4xl space-y-6">
      <Head title="Методика и выгрузки" subtitle="Как считаются показатели и что никогда не попадает в кабинет."
        csv={[{ id: "demand", title: "категории" }, { id: "skills", title: "навыки" }, { id: "fsp", title: "ФСП" }, { id: "salaries", title: "зарплаты" }]} />
      <Body>{(rep) => (
        <>
          <section className="card">
            <ol className="list-decimal space-y-3 pl-5 text-sm leading-relaxed text-brand-ink/85">
              {rep.methodology.map((m: string, i: number) => <li key={i}>{m}</li>)}
            </ol>
          </section>
          <section className="card space-y-2 text-sm text-brand-ink/80">
            <h2 className="text-lg font-bold text-brand-night">Доступ</h2>
            <p>Роль «ФСП» видит только агрегаты: ни карточек кандидатов, ни потребностей, ни приглашений поштучно. Каждое обращение к кабинету и каждая выгрузка записываются в журнал сервера.</p>
            <p>API: <a className="font-semibold text-brand hover:text-brand-soft" href="/api/docs#/fsp-cabinet" target="_blank" rel="noreferrer">/api/fsp-cabinet</a> — те же данные для BI федерации, CSV в кодировке UTF-8 с разделителем «;».</p>
            <p className="text-xs text-brand-ink/55">Отчёт сформирован {new Date(rep.generated_at).toLocaleString("ru-RU")}.</p>
          </section>
        </>
      )}</Body>
    </div>
  );
}
