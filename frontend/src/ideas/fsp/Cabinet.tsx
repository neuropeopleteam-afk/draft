// Кабинет ФСП (роль fsp_analyst): обезличенная аналитика платформы — только агрегаты, группы меньше 5 скрыты.
import { Suspense, useEffect, useState } from "react";
import { Link, Outlet, useOutletContext } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, DIRECTION_TITLES, GRADES, Seg, Stat, cleanCompanyName, dt, errText, range } from "../../components/ui";
import { api, apiDownload, tokenStore } from "../../lib/api";
import { BarList, Donut, Funnel, Heatmap, Legend, PairBars, RangeChart, StackBar, fk, fpct, ftr, fx, type Stage } from "../charts";
import { MODE_SHORT, Phase } from "../shared";
import { CameraStats } from "../../proctor/CameraStats";
import { useDemoUi } from "../../lib/juryMode";
import FspRankConverter from "../../components/FspRankConverter";
import { FspCabinet3DStage } from "../../components/Fsp3DShowcase";
import { NUMBERS } from "../../lib/numbers";
import { TalentMap } from "./TalentMap";

type Rep = any;
interface Ctx { rep: Rep | null; loading: boolean; error: string | null; days: string; setDays: (d: string) => void }

const PERIODS = [{ id: "all", title: "Всё время" }, { id: "180", title: "180 дней" }, { id: "90", title: "90 дней" }, { id: "30", title: "30 дней" }];
const KEY = "fsp_cabinet_days";
const DIRS = Object.entries(DIRECTIONS).map(([id, title]) => ({ id, title: id === "security" ? "ИБ" : title }));
const GRS = Object.entries(GRADES).map(([id, title]) => ({ id, title }));
const q = (days: string) => (days === "all" ? "" : `?days=${days}`);
/** Отклонение в процентах со знаком: «+4,2 %», «−10 %». */
const sgn = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}\u00A0%`;

const REPORT_STALE_MS = 120_000; // ≥ 60 с: общий кэш отчёта для обзора и всех вкладок кабинета ФСП
const REPORT_CACHE_PREFIX = "fsp_cabinet_report_v1:";

interface ReportCacheEntry {
  data: Rep;
  ts: number;
}

const reportMemCache = new Map<string, ReportCacheEntry>();
const reportInFlight = new Map<string, Promise<Rep>>();

function reportCacheKey(days: string): string {
  const tok = (tokenStore.get() ?? "anon").slice(-24);
  return `${tok}:${days}`;
}

function readCachedReport(days: string): Rep | null {
  const key = reportCacheKey(days);
  const now = Date.now();
  const mem = reportMemCache.get(key);
  if (mem && now - mem.ts < REPORT_STALE_MS) return mem.data;
  try {
    const raw = sessionStorage.getItem(REPORT_CACHE_PREFIX + key);
    if (raw) {
      const parsed = JSON.parse(raw) as ReportCacheEntry;
      if (parsed && parsed.data && now - parsed.ts < REPORT_STALE_MS) {
        reportMemCache.set(key, parsed);
        return parsed.data;
      }
    }
  } catch {
    /* sessionStorage может быть недоступен или переполнен */
  }
  return null;
}

function writeCachedReport(days: string, data: Rep): void {
  const key = reportCacheKey(days);
  const entry: ReportCacheEntry = { data, ts: Date.now() };
  reportMemCache.set(key, entry);
  try {
    sessionStorage.setItem(REPORT_CACHE_PREFIX + key, JSON.stringify(entry));
  } catch {
    /* игнорируем переполнение хранилища */
  }
}

function fetchReportShared(days: string): Promise<Rep> {
  const cached = readCachedReport(days);
  if (cached) return Promise.resolve(cached);
  const key = reportCacheKey(days);
  const inflight = reportInFlight.get(key);
  if (inflight) return inflight;
  const req = api<Rep>(`/fsp-cabinet/report${q(days)}`)
    .then((res) => {
      writeCachedReport(days, res);
      return res;
    })
    .finally(() => {
      reportInFlight.delete(key);
    });
  reportInFlight.set(key, req);
  return req;
}

/** Скелет аналитики кабинета ФСП на время загрузки отчёта (вместо пустых блоков). */
function ReportSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-busy="true" aria-live="polite" data-testid="fsp-report-skeleton">
      <span className="sr-only">Загрузка…</span>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-5 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card min-w-0 space-y-2.5">
            <div className="h-3 w-3/5 animate-pulse rounded bg-brand-blush/60" />
            <div className="h-7 w-1/2 animate-pulse rounded bg-brand-blush/50" />
            <div className="h-3 w-4/5 animate-pulse rounded bg-brand-blush/35" />
          </div>
        ))}
      </div>
      <div className="card space-y-3">
        <div className="h-5 w-2/5 animate-pulse rounded bg-brand-blush/60" />
        <div className="h-4 w-full animate-pulse rounded bg-brand-blush/35" />
        <div className="h-4 w-5/6 animate-pulse rounded bg-brand-blush/35" />
        <div className="h-4 w-4/6 animate-pulse rounded bg-brand-blush/35" />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="card min-w-0 space-y-4">
            <div className="space-y-1.5">
              <div className="h-5 w-1/2 animate-pulse rounded bg-brand-blush/60" />
              <div className="h-3.5 w-3/4 animate-pulse rounded bg-brand-blush/35" />
            </div>
            <div className="h-36 animate-pulse rounded-2xl bg-brand-blush/30" />
          </div>
        ))}
      </div>
      <div className="card space-y-4">
        <div className="h-5 w-1/2 animate-pulse rounded bg-brand-blush/60" />
        <div className="h-48 animate-pulse rounded-2xl bg-brand-blush/25" />
      </div>
    </div>
  );
}

/** Обёртка разделов: один запрос /fsp-cabinet/report на период (кэш ≥ 60 с + дедупликация), общий для всех вкладок кабинета. */
export function FspReportLayout() {
  const [days, setDaysS] = useState(() => localStorage.getItem(KEY) ?? "all");
  const [data, setData] = useState<Rep | null>(() => readCachedReport(days));
  const [loading, setLoading] = useState<boolean>(() => !readCachedReport(days));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const cached = readCachedReport(days);
    if (cached) {
      setData(cached);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetchReportShared(days)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(errText(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const setDays = (d: string) => {
    localStorage.setItem(KEY, d);
    setDaysS(d);
  };
  return (
    <Suspense fallback={<ReportSkeleton />}>
      <Outlet context={{ rep: data, loading, error, days, setDays } satisfies Ctx} />
    </Suspense>
  );
}

const useRep = () => useOutletContext<Ctx>();

function Head({ title, subtitle, csv }: { title: string; subtitle: string; csv?: { id: string; title: string }[] }) {
  const { days, setDays, loading, rep } = useRep();
  const [err, setErr] = useState<string | null>(null);
  async function download(id: string) {
    setErr(null);
    try { await apiDownload(`/fsp-cabinet/export/${id}.csv${q(days)}`, `fsp_${id}.csv`); } catch (e) { setErr(errText(e)); }
  }
  const fspRegions = (NUMBERS as any)?.fsp_facts?.regions ?? 89;
  const fspClaim = (NUMBERS as any)?.fsp_facts?.claim_ru ?? "89 действующих региональных представительств ФСП в России";
  return (
    <div className="space-y-4">
      <div className="fsp-stage-card overflow-hidden rounded-3xl p-5 sm:p-6">
        <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <div className="min-w-0 flex-1 [&_h1]:text-white [&_p]:text-white/80">
            <p className="mb-1.5 inline-flex items-center gap-2 font-mono text-[11px] font-bold uppercase tracking-[0.14em] text-[#B8B4FF]" title={fspClaim}>
              <i className="fsp-pulse-dot" aria-hidden="true" />
              ФСП: {fspRegions} региональных представительств
            </p>
            <PageTitle title={title} subtitle={subtitle} />
          </div>
          <FspCabinet3DStage kind="medallion" badge={`ФСП · ${fspRegions} представительств`} sub="Аналитика и кубки" />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="hidden sm:inline-flex"><Seg label="Период" value={days} onChange={setDays} options={PERIODS} /></span>
        <label className="flex items-center gap-2 text-sm sm:hidden">
          <span className="font-semibold text-brand-night">Период</span>
          <select className="input w-auto py-2" value={days} onChange={(e) => setDays(e.target.value)}>
            {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        </label>
        <span className="text-xs text-brand-ink/65" aria-live="polite">
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
  if (loading || !rep) return <ReportSkeleton />;
  return <>{children(rep)}</>;
}

function Card({ title, sub, children, more }: { title: string; sub?: string; children: React.ReactNode; more?: { to: string; label: string } }) {
  return (
    <section className="card min-w-0 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold text-brand-night">{title}</h2>
          {sub && <p className="mt-1 text-sm text-brand-ink/65">{sub}</p>}
        </div>
        {more && <Link to={more.to} className="text-sm font-semibold text-brand hover:text-brand-soft">{more.label} →</Link>}
      </div>
      {children}
    </section>
  );
}

function DemoNote({ rep }: { rep: Rep }) {
  const demoUi = useDemoUi();
  if (!demoUi || !(rep.overview.demo_share >= 0.99)) return null;
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
  const { days } = useRep();
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
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-5 lg:grid-cols-4">
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
              <Card title="ФСП и приглашения" sub="Доля кандидатов, получивших приглашение" more={{ to: "/fsp/effect", label: "Подробнее" }}>
                <div className="grid grid-cols-3 gap-2">
                  <Donut value={fsp.invite_rate} label="с достижениями ФСП" tone="night" />
                  <Donut value={nofsp.invite_rate} label="без истории ФСП (нейтрально)" tone="lavender" />
                  <Donut value={o.acceptance_rate} label="приглашений принято (из отвеченных)" tone="brand" />
                </div>
              </Card>
              <Card title="Спрос по направлениям" sub="Приглашения-офферы за период" more={{ to: "demand", label: "Категории и навыки" }}>
                <BarList rows={byDir.map((d) => ({ key: d.id, label: DIRECTION_TITLES[d.id], value: d.v }))} labelWidth="11rem" />
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
            <TalentMap data={rep.regions_map} />
            <FspRankConverter />
            <CameraStats days={days === "all" ? null : Number(days)} />
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

const GRADE_RANK: Record<string, number> = { intern: 0, junior: 1, middle: 2, senior: 3, lead: 4, principal: 5 };

export function FspDemand() {
  const [metric, setMetric] = useState<(typeof METRICS)[number]["id"]>("invitations");
  const [allSkills, setAllSkills] = useState(false);
  const [hideEmptyCats, setHideEmptyCats] = useState(false);
  const m = METRICS.find((x) => x.id === metric)!;
  return (
    <div className="max-w-6xl space-y-6 pb-12">
      <Head title="Спрос работодателей" subtitle="Какие категории и навыки нужны компаниям: потребности, приглашения-офферы и предложение подтверждённых кандидатов."
        csv={[{ id: "demand", title: "категории" }, { id: "skills", title: "навыки" }]} />
      <Body>{(rep) => {
        const rawCats: any[] = rep.demand.categories ?? [];
        const cats = [...rawCats].sort((a, b) => {
          if (a.direction !== b.direction) return String(a.direction).localeCompare(String(b.direction));
          return (GRADE_RANK[a.grade] ?? 99) - (GRADE_RANK[b.grade] ?? 99);
        });
        const visibleCats = hideEmptyCats
          ? cats.filter((c) => (c.needs ?? 0) > 0 || (c.invitations ?? 0) > 0 || (c.supply ?? 0) > 0)
          : cats;
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
              {noGrade.length > 0 && <p className="text-xs text-brand-ink/65">Потребности без грейда: {noGrade.map(([d, n]) => `${DIRECTION_TITLES[d] ?? d} — ${n}`).join(", ")}.</p>}
            </Card>
            <Card title="Навыки в потребностях" sub="Сколько потребностей требуют навык (обязательно и желательно) и как часто приглашают тех, кто подтвердил его на платформе.">
              <Legend items={[{ tone: "brand", label: "обязательно" }, { tone: "soft", label: "желательно" }]} />
              <ul className="space-y-3">
                {skills.map((s) => (
                  <li key={s.tag} className="grid gap-x-3 gap-y-1 rounded-xl border border-brand-night/5 bg-[#F8F9FF] px-3.5 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)_15rem] sm:items-center">
                    <span className="text-sm font-semibold text-brand-night">{s.title}</span>
                    <span className="flex items-center gap-2.5">
                      <StackBar max={smax} parts={[{ value: s.needs_required, tone: "brand", label: "обязательно" }, { value: s.needs_desired, tone: "soft", label: "желательно" }]} />
                      <span className="w-8 shrink-0 text-right font-mono text-sm font-bold tabular-nums text-brand-night">{s.needs_required + s.needs_desired}</span>
                    </span>
                    <span className="text-xs text-brand-ink/70">
                      компаний <b className="font-mono text-brand-night">{s.companies}</b> · подтв. <b className="font-mono text-brand-night">{fk(s.supply_confirmed)}</b> · офферы <b className="font-mono text-brand">{fpct(s.invite_rate_with_skill)}</b>
                    </span>
                  </li>
                ))}
              </ul>
              {skillsAll.length > 12 && (
                <button className="btn-ghost !px-3.5 !py-1.5 text-xs" onClick={() => setAllSkills(!allSkills)}>
                  {allSkills ? "Свернуть" : `Показать все навыки (${skillsAll.length})`}
                </button>
              )}
            </Card>
            <Card title="Таблица по категориям" sub="Сводная матрица спроса компаний, предложения подтверждённых специалистов и конверсии приглашений по грейдам.">
              <div className="flex flex-wrap items-center justify-between gap-2 pb-1">
                <span className="text-xs text-brand-ink/65">
                  Показано категорий: <b className="font-mono text-brand-night">{visibleCats.length}</b> из {cats.length}
                </span>
                <button
                  type="button"
                  onClick={() => setHideEmptyCats((v) => !v)}
                  className="rounded-lg border border-brand-night/15 bg-[#F4F6FC] px-3 py-1 text-xs font-semibold text-brand-night transition hover:border-brand/40 hover:bg-brand-blush/60"
                >
                  {hideEmptyCats ? "Показать все категории" : "Скрыть пустые строки (0 потребностей)"}
                </button>
              </div>
              <div className="overflow-x-auto rounded-2xl border border-brand-night/10">
                <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-brand-night/10 bg-gradient-to-r from-[#EEF1FE] via-[#F4F6FF] to-[#EEF1FE] text-[11px] font-bold uppercase tracking-[0.04em] text-brand-plum">
                      <th className="py-3 pl-3.5 pr-2">Категория</th>
                      <th className="px-2 py-3 text-right">Потребн.</th>
                      <th className="px-2 py-3 text-right">Компании</th>
                      <th className="px-2 py-3 text-right">Приглаш.</th>
                      <th className="px-2 py-3 text-right">Кандидаты</th>
                      <th className="px-2 py-3 text-right">Приглашены</th>
                      <th className="px-2 py-3 text-right">Приняли</th>
                      <th className="whitespace-nowrap py-3 pl-2 pr-3.5 text-right">Медиана рынка</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-night/8 font-mono text-[13px] tabular-nums">
                    {visibleCats.map((c) => {
                      const isEmpty = !c.needs && !c.invitations;
                      const [dirName, gradeName] = String(c.title ?? "").split(" · ");
                      return (
                        <tr
                          key={c.category_id}
                          className={`transition-colors hover:bg-[#F2F5FF] ${isEmpty ? "bg-gray-50/50 text-brand-ink/50" : "bg-white text-brand-night"}`}
                        >
                          <td className="py-2.5 pl-3.5 pr-2 font-sans">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className={`font-semibold ${isEmpty ? "text-brand-ink/60" : "text-brand-night"}`}>{dirName || c.title}</span>
                              {gradeName && (
                                <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-bold ${
                                  isEmpty
                                    ? "bg-gray-100 text-gray-500"
                                    : "border border-brand/20 bg-brand-blush/70 text-brand-strong"
                                }`}>
                                  {gradeName}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-2 py-2.5 text-right font-semibold">{c.needs}</td>
                          <td className="px-2 py-2.5 text-right">{c.companies}</td>
                          <td className="px-2 py-2.5 text-right font-bold">{c.invitations}</td>
                          <td className="px-2 py-2.5 text-right">{fk(c.supply)}</td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-right">
                            <span>{fk(c.invited_candidates)}</span>
                            {c.invite_rate != null && (
                              <span className="ml-1 inline-flex rounded bg-brand/10 px-1.5 py-0.5 text-[11px] font-bold text-brand-strong">
                                {fpct(c.invite_rate)}
                              </span>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-right">
                            <span>{fk(c.accepted_candidates)}</span>
                            {c.accept_rate != null && (
                              <span className="ml-1 inline-flex rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] font-bold text-emerald-700">
                                {fpct(c.accept_rate)}
                              </span>
                            )}
                          </td>
                          <td className="whitespace-nowrap py-2.5 pl-2 pr-3.5 text-right font-sans">
                            {c.market_median ? (
                              <span className="inline-flex rounded-lg bg-[#EEF1FE] px-2.5 py-1 font-mono text-xs font-bold text-brand-night">
                                {ftr(c.market_median)}
                              </span>
                            ) : (
                              <span className="text-brand-ink/40">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
            <TalentMap data={rep.regions_map} />
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
      <Head title="Эффект соревнований ФСП" subtitle="Какие дисциплины, разряды, результаты и уровни соревнований ФСП ведут к приглашениям. Учитываются только достижения, подтверждённые реестром ФСП."
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
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:gap-5 [&>*:last-child]:col-span-2 sm:[&>*:last-child]:col-span-1">
              <Stat label="С достижениями ФСП" value={fpct(fsp.invite_rate)} hint={`приглашены ${fk(fsp.invited)} из ${fk(fsp.candidates)}`} />
              <Stat label="Без истории ФСП" value={fpct(nofsp.invite_rate)} hint={`приглашены ${fk(nofsp.invited)} из ${fk(nofsp.candidates)} · без штрафа`} />
              <Stat label="Отношение" value={fx(fsp.lift_vs_no_fsp)} hint={`с поправкой на категорию ${fx(fsp.adjusted_ratio)} к ожидаемому`} />
            </div>
            <Card title="По направлениям" sub="Доля приглашённых среди кандидатов направления">
              <PairBars a={{ label: "с достижениями ФСП", tone: "night" }} b={{ label: "без истории ФСП", tone: "lavender" }}
                rows={fe.by_direction.map((d: any) => ({ key: d.direction, label: d.title, a: d.fsp.invite_rate, b: d.no_fsp.invite_rate,
                  aText: d.fsp.invite_rate == null ? (d.fsp.candidates === 0 ? "нет" : "< 5") : undefined,
                  bText: d.no_fsp.invite_rate == null ? (d.no_fsp.candidates === 0 ? "нет" : "< 5") : undefined }))} />
            </Card>
            <p className="flex items-center gap-2 text-xs text-brand-ink/65"><span className="h-3 border-l-2 border-dashed border-brand-night/50" aria-hidden /> Пунктир на графиках ниже — доля приглашённых без истории ФСП ({fpct(base)}).</p>
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
              в категории каждого кандидата. Кубки работодателей (мероприятия платформы) здесь не учитываются — они в «Воронках».
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
              <div className="overflow-x-auto rounded-2xl border border-brand-night/10">
                <table className="w-full min-w-[42rem] border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-brand-night/10 bg-gradient-to-r from-[#EEF1FE] via-[#F4F6FF] to-[#EEF1FE] text-[11px] font-bold uppercase tracking-[0.08em] text-brand-plum">
                      <th className="py-3 pl-4 pr-3">Направление</th>
                      <th className="px-3 py-3 text-right">Офферы</th>
                      <th className="px-3 py-3 text-right">«От», p25</th>
                      <th className="px-3 py-3 text-right">«От», медиана</th>
                      <th className="px-3 py-3 text-right">«До», медиана</th>
                      <th className="px-3 py-3 text-right">«До», p75</th>
                      <th className="py-3 pl-3 pr-4 text-right">Середина</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-night/8 font-mono text-[13px] tabular-nums">
                    {s.directions.map((d: any) => (
                      <tr key={d.direction} className="bg-white transition-colors hover:bg-[#F2F5FF]">
                        <td className="py-2.5 pl-4 pr-3 font-sans font-semibold text-brand-night">{d.title}</td>
                        <td className="px-3 py-2.5 text-right">{fk(d.offers)}</td>
                        {d.suppressed ? <td colSpan={5} className="py-2.5 pr-4 text-right font-sans text-xs text-brand-ink/60">скрыто: {d.reason}</td> : (
                          <>
                            <td className="px-3 py-2.5 text-right">{ftr(d.from_p25)}</td><td className="px-3 py-2.5 text-right">{ftr(d.from_median)}</td>
                            <td className="px-3 py-2.5 text-right">{ftr(d.to_median)}</td><td className="px-3 py-2.5 text-right">{ftr(d.to_p75)}</td>
                            <td className="py-2.5 pl-3 pr-4 text-right">
                              <span className="inline-flex rounded-lg bg-[#EEF1FE] px-2.5 py-1 font-mono text-xs font-bold text-brand-night">{ftr(d.mid_median)}</span>
                            </td>
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
            <p className="text-xs text-brand-ink/65">Рынок — открытые данные рынка и офферы на платформе, p25–p75 по категории.</p>
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
              <Card title="С достижениями ФСП"><Funnel stages={f.fsp} tone="night" /></Card>
              <Card title="Без истории ФСП"><Funnel stages={f.no_fsp} tone="lavender" /></Card>
            </div>
            <Card title="Конверсии рядом" sub="Доля перешедших на следующий этап">
              <PairBars a={{ label: "с ФСП", tone: "night" }} b={{ label: "без ФСП", tone: "lavender" }}
                rows={[1, 2, 3].map((i) => ({ key: String(i), label: f.all[i].title, a: conv(f.fsp, i), b: conv(f.no_fsp, i) }))} />
            </Card>
            <Card title="Все кандидаты"><Funnel stages={f.all} tone="plum" /></Card>
            <p className="text-xs text-brand-ink/65">{f.note}</p>
          </>
        );
      }}</Body>
    </div>
  );
}

// ------------------------------------------------------------------ кубки

export function FspCups() {
  const demoUi = useDemoUi();
  return (
    <div className="max-w-6xl space-y-6">
      <Head title="Кубки работодателей" subtitle="Кубок — публичное мероприятие платформы: компания и условия открыты, участники — только числом. Места записываются в паспорт ФСП (подтверждено платформой)." />
      <Body>{(rep) => {
        const cups: any[] = (rep.cups ?? []).filter((c: any) => demoUi || (!c.is_demo && !/^Демо(?:\s+жюри)?:/i.test(c.company ?? "")));
        const tours: any[] = (rep.tournaments ?? []).filter((t: any) => demoUi || (!t.is_demo && !/^Демо(?:\s+жюри)?:/i.test(t.company ?? "")));
        return (
          <>
          {tours.length > 0 && <Tournaments items={tours} k={rep.k} />}
          {!cups.length ? <Alert kind="info">За выбранный период кубков не было.</Alert> : (
          <div className="grid gap-4 lg:grid-cols-2">
            {cups.map((c) => (
              <article key={c.id} className="card space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{c.category_title} · {MODE_SHORT[c.mode] ?? c.mode}</p>
                    <h2 className="mt-1 text-lg font-bold text-brand-night">{c.title}</h2>
                    <p className="text-sm text-brand-ink/65">{cleanCompanyName(c.company)}</p>
                  </div>
                  <Phase p={c.phase} />
                </div>
                <p className="text-sm text-brand-ink/70">{dt(c.starts_at)} — {dt(c.ends_at)} · {range(c.salary_from, c.salary_to)} · приглашения топ-{c.invite_top_n}</p>
                <dl className="grid grid-cols-3 gap-2 text-center sm:grid-cols-5">
                  {[["Участники", c.participants], ["С местом", c.placed], ["Приглашены", c.invited], ["Приняли", c.accepted], ["В паспорте", c.passport_written]].map(([t, v]) => (
                    <div key={t as string} className="rounded-xl bg-[#EEF1FC] px-2 py-2">
                      <dt className="text-xs font-semibold uppercase tracking-wide text-brand-ink/65">{t}</dt>
                      <dd className="mt-0.5 text-base font-bold tabular-nums text-brand-night">{fk(v as number | null)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="text-xs text-brand-ink/65">
                  {c.score_median_pct != null ? `Медиана балла ${c.score_median_pct} %. ` : ""}
                  {c.passport_pending ? `Ждут связки с ФСП ID: ${fk(c.passport_pending)}.` : ""}
                </p>
              </article>
            ))}
          </div>
          )}
          </>
        );
      }}</Body>
    </div>
  );
}

/** Н5: отборочные турниры «Компания × ФСП» под вакансии — дисциплина, стек, задания, приз; участники только числом. */
function Tournaments({ items, k }: { items: any[]; k: number }) {
  return (
    <section className="space-y-3" aria-labelledby="fsp-tournaments">
      <div>
        <h2 id="fsp-tournaments" className="flex flex-wrap items-center gap-2 text-lg font-bold text-brand-night">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-brand-night px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-[0.14em] text-white"><span className="h-1.5 w-1.5 rounded-full bg-brand" aria-hidden="true" />ФСП</span>
          Отборочные турниры «Компания × ФСП»
        </h2>
        <p className="mt-1 text-sm text-brand-ink/65">Кубки, запущенные работодателями под конкретную вакансию: три задания банка под обязательный стек, топ-5 — прямой оффер и очки в рейтинг ФСП. Группы меньше {k} участников — без чисел.</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {items.map((t) => (
          <article key={t.id} className="card space-y-3 border-l-4 border-brand">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{t.discipline} · {t.category_title}</p>
                <h3 className="mt-1 text-base font-bold text-brand-night">{t.title}</h3>
                <p className="text-sm text-brand-ink/65">{cleanCompanyName(t.company)} · {t.position_title}</p>
              </div>
              <Phase p={t.phase} />
            </div>
            {t.stack?.length > 0 && <p className="flex flex-wrap gap-1.5">{t.stack.map((s: string) => <span key={s} className="rounded-full bg-[#EEF1FC] px-2.5 py-0.5 text-xs font-semibold text-brand-night">{s}</span>)}</p>}
            <ol className="list-decimal space-y-0.5 pl-5 text-sm text-brand-ink/80">{t.tasks.map((x: string, i: number) => <li key={i}>{x}</li>)}</ol>
            <dl className="grid grid-cols-3 gap-2 text-center">
              {[["Участники", t.participants], ["Оценено", t.scored], ["Приглашены", t.invited]].map(([n, v]) => (
                <div key={n as string} className="rounded-xl bg-[#EEF1FC] px-2 py-2">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-brand-ink/65">{n}</dt>
                  <dd className="mt-0.5 text-base font-bold tabular-nums text-brand-night">{fk(v as number | null)}</dd>
                </div>
              ))}
            </dl>
            <p className="text-xs leading-relaxed text-brand-ink/65">{t.prize}{t.ends_at ? ` · до ${dt(t.ends_at)}` : ""}{t.best_pct != null ? ` · лучший балл ${t.best_pct} %` : ""}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ методика

export function FspMethod() {
  return (
    <div className="max-w-4xl space-y-6">
      <Head title="Методика и выгрузки" subtitle="Как считаются показатели и что не попадает в кабинет."
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
            <p className="text-xs text-brand-ink/65">Отчёт сформирован {new Date(rep.generated_at).toLocaleString("ru-RU")}.</p>
          </section>
        </>
      )}</Body>
    </div>
  );
}
