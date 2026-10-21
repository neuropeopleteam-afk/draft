import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, GRADE_TITLE_ALL, Loading, catTitle, dt, plainText, range, rub, useApi } from "../../components/ui";
import HhMarketSkills, { type HhMarket } from "../../components/HhMarketSkills";  // Я12б: «Что сейчас просит рынок» (hh.ru)
import { ThetaScale } from "../../components/ThetaScale";

/** Обратная связь после теста: карта навыков, спрос работодателей категории, маршрут роста, дисциплины ФСП. */

interface Aspect { title: string; n: number; score: number | null; status: string }
interface Topic {
  tag: string; title: string; block: string; n: number; scored: number; pending: number; score: number | null;
  expected: number | null; relative: string | null; status: string; confidence: string; level: string | null; aspects: Aspect[];
}
interface DemandItem { tag: string; title: string; required: number; desired: number; share: number; status: string; status_title: string; testable: boolean; test_score: number | null }
interface Step { kind: string; title: string; text: string; tags: string[]; source?: string; action?: { title: string; href: string } | null }
/** D3 п. 4: два списка «подтянуть» подписаны источником — тест или спрос работодателей (не путать жюри). */
const SOURCE_TEST = "Слабее всего по тесту", SOURCE_DEMAND = "Востребовано у работодателей в вашей категории";
const stepSource = (s: Step) => s.source ?? (s.kind === "topic" ? SOURCE_TEST : s.kind === "demand" ? SOURCE_DEMAND : null);
interface Comp { discipline: string; title: string; score: number; reasons: string[]; your_level: string | null; your_level_title: string | null; next_step: string; peers?: { category_size: number; with_discipline: number } }
export interface FeedbackData {
  available: boolean; message?: string; source?: string;
  session?: { id: string | null; direction: string; direction_title: string; claimed_grade: string; grade_title: string; theta: number | null; se: number | null; confirmed: boolean | null; finished_at: string | null; category_id: string | null; integrity: { level: string; title: string; reasons: string[]; note?: string } | null };
  skill_map?: { topics: Topic[]; summary: { topics: number; strong: number; ok: number; gap: number; pending: number; best: string[]; weakest: string[] }; note: string };
  demand?: { scope: string; scope_title: string; sources: number; sources_in_category: number; items: DemandItem[]; full_match: number; with_required: number; avg_required_coverage: number | null; note: string };
  route?: Step[]; competitions?: Comp[]; fsp_calendar_url?: string;
  market_hh?: HhMarket | null;
}

const STATUS: Record<string, [string, string, string]> = {
  strong: ["Уверенно", "bg-emerald-50 text-emerald-800 ring-emerald-200", "bg-emerald-500"],
  ok: ["В целом освоено", "bg-[#EEF1FC] text-brand-night ring-brand-lavender/30", "bg-brand-lavender"],
  gap: ["Пробел", "bg-brand-blush/50 text-brand-plum ring-brand/20", "bg-brand"],
  pending: ["На проверке", "bg-brand-night/5 text-brand-ink/70 ring-brand-night/10", "bg-brand-night/30"],
};
const DEMAND: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-800 ring-emerald-200", weak: "bg-brand-blush/50 text-brand-plum ring-brand/20",
  declared: "bg-[#EEF1FC] text-brand-night ring-brand-lavender/30", missing: "bg-brand-night/5 text-brand-ink/70 ring-brand-night/10",
};
const DEMAND_LEVEL: Record<string, string> = { confirmed: "T1", weak: "T1", declared: "T0", missing: "none" };
const REL: Record<string, string> = { above: "выше ожидаемого для вашего уровня", below: "ниже ожидаемого для вашего уровня" };
const GRADE_RU: Record<string, string> = { none: "без грейда", ...GRADE_TITLE_ALL };
const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}\u00A0%`);
const tasks = (n: number) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? "задание" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "задания" : "заданий"}`;

function Chip({ s, children }: { s: string; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${s}`}>{children}</span>;
}

/** Полоса: доля верного; черта — ожидаемая доля для общего уровня θ. */
function Bar({ score, expected, status }: { score: number | null; expected: number | null; status: string }) {
  return (
    <div className="relative h-2.5 w-full rounded-full bg-brand-night/5" aria-hidden="true">
      {score != null && <div className={`h-2.5 rounded-full ${STATUS[status]?.[2] ?? "bg-brand-lavender"}`} style={{ width: `${Math.max(3, score * 100)}%` }} />}
      {expected != null && <div className="absolute -top-1 w-0.5 rounded bg-brand-night/70" style={{ left: `calc(${expected * 100}% - 1px)`, height: "18px" }} />}
    </div>
  );
}

function TopicRow({ t }: { t: Topic }) {
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-brand-night">{t.title === "other" ? "Прочие темы" : t.title}</p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-brand-ink/65">
          <span>{tasks(t.n)}{t.level ? ` · уровень заданий ${GRADE_RU[t.level]}` : ""}</span>
          <Chip s={STATUS[t.status]?.[1] ?? STATUS.pending[1]}>{STATUS[t.status]?.[0] ?? t.status}</Chip>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-3">
        <div className="flex-1"><Bar score={t.score} expected={t.expected} status={t.status} /></div>
        <span className="w-12 text-right text-sm font-bold text-brand-night">{pct(t.score)}</span>
      </div>
      <p className="mt-1 text-xs text-brand-ink/65">
        {t.expected != null ? `Ожидаемо для вашего уровня — ${pct(t.expected)}` : "Результат по фактам теста"}
        {t.relative && REL[t.relative] ? ` · ${REL[t.relative]}` : ""}
        {t.pending ? ` · на проверке у эксперта: ${t.pending}` : ""}
        {t.confidence === "low" ? " · мало заданий, оценка ориентировочная" : ""}
      </p>
      {t.aspects.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {t.aspects.map((a) => (
            <span key={a.title} title={a.score != null ? `${pct(a.score)}` : "на проверке"}
              className={`rounded-md px-1.5 py-0.5 text-xs ring-1 ${STATUS[a.status]?.[1] ?? STATUS.pending[1]}`}>{a.title}</span>
          ))}
        </div>
      )}
    </li>
  );
}

function SkillMap({ fb }: { fb: FeedbackData }) {
  const topics = fb.skill_map?.topics ?? [];
  const groups = [["common", "Общий блок"], ["direction", fb.session?.direction_title ? `Направление ${fb.session.direction_title}` : "Направление"]] as const;
  return (
    <section className="card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold text-brand-night">Карта навыков по темам</h2>
        <p className="text-xs text-brand-ink/65">Полоса — доля баллов, черта — ожидаемая доля для вашего общего уровня</p>
      </div>
      {groups.map(([b, title]) => {
        const list = topics.filter((t) => t.block === b);
        if (!list.length) return null;
        return (
          <div key={b} className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{title}</p>
            <ul className="divide-y divide-brand-night/5">{list.map((t) => <TopicRow key={t.tag} t={t} />)}</ul>
          </div>
        );
      })}
      <p className="mt-3 text-xs text-brand-ink/65">{plainText(fb.skill_map?.note ?? "")}</p>
    </section>
  );
}

function Demand({ d }: { d: NonNullable<FeedbackData["demand"]> }) {
  if (!d.items.length) return (
    <section className="card"><h2 className="font-bold text-brand-night">Что требуют работодатели</h2>
      <p className="mt-2 text-sm text-brand-ink/65">Активных потребностей и вакансий по вашему направлению пока нет.</p></section>
  );
  return (
    <section className="card">
      <h2 className="font-bold text-brand-night">Что требуют работодатели — {d.scope_title}</h2>
      <p className="mt-1 text-sm text-brand-ink/65">
        Источников: {d.sources} — активные потребности работодателей и опубликованные вакансии на платформе.
        {d.with_required > 0 && <> Все обязательные навыки подтверждены в <b>{d.full_match} из {d.with_required}</b>; в среднем закрыто {pct(d.avg_required_coverage)} обязательных.</>}
      </p>
      <ul className="mt-3 divide-y divide-brand-night/5 text-sm">
        {d.items.map((x) => (
          <li key={x.tag} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2 sm:grid-cols-[minmax(0,1fr)_15rem_auto]">
            <span className="min-w-0 break-words font-medium text-brand-night">{x.title}</span>
            <span className="order-3 col-span-2 flex items-center gap-2 whitespace-nowrap text-xs text-brand-ink/65 sm:order-none sm:col-span-1">
              <span className="h-1.5 w-16 shrink-0 rounded-full bg-brand-night/5"><span className="block h-1.5 rounded-full bg-brand-lavender" style={{ width: `${x.share * 100}%` }} /></span>
              {x.required + x.desired} из {d.sources}{x.required ? ` · обязательно в ${x.required}` : " · желательно"}
            </span>
            {/* Без кода уровня и без второй плашки; на 390 px подпись переносится (была горизонтальная прокрутка 425 px) */}
            <span className="flex min-w-0 max-w-[11rem] items-center justify-self-end sm:max-w-none" title={DEMAND_LEVEL[x.status] === "T1" ? "Проверено на платформе" : DEMAND_LEVEL[x.status] === "T0" ? "Указано вами, не проверено" : undefined}><Chip s={`${DEMAND[x.status]} max-w-full whitespace-normal break-words text-right`}>{plainText(x.status_title)}</Chip></span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-brand-ink/65">{plainText(d.note)}</p>
    </section>
  );
}

function Route({ steps }: { steps: Step[] }) {
  return (
    <section className="card border-brand/25 bg-brand-blush/15">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold text-brand-night">Маршрут роста: что сделать дальше</h2>
        <span className="text-xs font-semibold text-brand-plum">Прямые действия для повышения вилки и места в выдаче</span>
      </div>
      <ol className="mt-3 space-y-3">
        {steps.map((s, i) => (
          <li key={i} className="flex flex-wrap items-start justify-between gap-3 rounded-xl bg-white p-3.5 shadow-sm ring-1 ring-brand-night/5">
            <div className="flex min-w-0 flex-1 gap-3">
              <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-strong text-xs font-bold text-white">{i + 1}</span>
              <div className="min-w-0">
                {stepSource(s) && <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender" data-testid="route-source">{stepSource(s)}</p>}
                <p className="font-semibold text-brand-night">{s.title}</p>
                <p className="mt-0.5 text-sm text-brand-ink/70">{plainText(s.text)}</p>
              </div>
            </div>
            {s.action?.href && (
              <Link to={s.action.href} className={i === 0 ? "btn-primary shrink-0 !px-4 !py-2 text-xs" : "btn-ghost shrink-0 !px-3.5 !py-1.5 text-xs"}>
                {s.action.title}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function Competitions({ list, url }: { list: Comp[]; url?: string }) {
  return (
    <section className="card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold text-brand-night">Соревнования ФСП</h2>
        {url && <a className="text-sm font-semibold text-brand underline" href={url} target="_blank" rel="noreferrer">Календарь соревнований ФСП</a>}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {list.map((c, i) => (
          <div key={c.discipline} className={`rounded-xl border p-4 ${i === 0 ? "border-brand/30 bg-brand-blush/20" : "border-brand-night/10"}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{i === 0 ? "Рекомендуем в первую очередь" : "Дополнительно"}</p>
            <p className="mt-1 font-bold text-brand-night">{c.title}</p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-brand-ink/75">{c.reasons.map((r, k) => <li key={k}>{r}</li>)}</ul>
            <p className="mt-2 text-sm text-brand-ink/75">{c.your_level_title ? <>Ваш лучший уровень: <b>{c.your_level_title}</b>. </> : null}{c.next_step}</p>
            {c.peers && c.peers.category_size > 0 && <p className="mt-1 text-xs text-brand-ink/65">В вашей категории достижения в этой дисциплине у {c.peers.with_discipline} из {c.peers.category_size} кандидатов.</p>}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-brand-ink/65">Достижения ФСП, подтверждённые реестром, дают бонус к месту в рейтинге категории и видны работодателю. Подтвердить их можно в разделе <Link className="underline" to="/candidate/fsp">«Паспорт ФСП»</Link>.</p>
    </section>
  );
}

/** P1 (А2): блок «Спрос на ваш профиль и чего не хватает до приглашений» — потребности категории, медианная вилка и 2 навыка для роста в подборках. */
export function DemandGapBanner({ fb: fbProp }: { fb?: FeedbackData | null }) {
  const { data: fbLoaded } = useApi<FeedbackData>(fbProp === undefined ? "/assessment/feedback" : null);
  const fb = fbProp ?? fbLoaded;
  if (!fb?.available || !fb.demand) return null;
  const d = fb.demand;
  const topMissing = (d.items ?? [])
    .filter((x) => x.status !== "confirmed")
    .sort((a, b) => (b.required * 2 + b.desired) - (a.required * 2 + a.desired))
    .slice(0, 2);
  const hhSal = (fb.market_hh as any)?.salary;
  const needsCount = d.sources_in_category || d.sources || 0;
  return (
    <section className="card space-y-3 border-brand/25 bg-gradient-to-r from-[#F4F6FC] to-white" data-testid="candidate-demand-gap">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand">Аналитика спроса на ваш профиль</p>
          <h2 className="mt-0.5 text-base font-bold text-brand-night">Спрос на ваш профиль и чего не хватает до приглашений</h2>
        </div>
        <span className="rounded-full bg-[#E6EAFC] px-2.5 py-1 text-xs font-semibold text-brand-night">
          {catTitle(fb.session?.category_id)}
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-white p-3 ring-1 ring-brand-night/10">
          <p className="text-xs font-semibold text-brand-ink/65">Потребностей и вакансий</p>
          <p className="mt-1 text-xl font-extrabold text-brand-night">{needsCount}</p>
          <p className="text-xs text-brand-ink/65">ищут вашу категорию на платформе</p>
        </div>
        <div className="rounded-xl bg-white p-3 ring-1 ring-brand-night/10">
          <p className="text-xs font-semibold text-brand-ink/65">Ориентир вилки категории</p>
          <p className="mt-1 text-lg font-extrabold text-brand-night">
            {hhSal?.median ? rub(hhSal.median) : hhSal?.from || hhSal?.to ? range(hhSal.from, hhSal.to) : "по категории"}
          </p>
          <p className="text-xs text-brand-ink/65">{hhSal?.from && hhSal?.to ? `вилка ${range(hhSal.from, hhSal.to)}` : "открытые данные рынка и офферы"}</p>
        </div>
        <div className="rounded-xl bg-white p-3 ring-1 ring-brand-night/10">
          <p className="text-xs font-semibold text-brand-ink/65">Покрытие обязательного стека</p>
          <p className="mt-1 text-xl font-extrabold text-brand-night">{pct(d.avg_required_coverage)}</p>
          <p className="text-xs text-brand-ink/65">полное совпадение: {d.full_match} из {d.with_required}</p>
        </div>
      </div>
      {topMissing.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-brand-blush/30 px-3.5 py-2.5 text-sm">
          <p className="text-brand-night">
            <b>2 навыка, подтверждение которых сильнее всего поднимет вас в подборках:</b>{" "}
            {topMissing.map((x) => `${x.title} (в ${x.required + x.desired} из ${d.sources} вакансий)`).join(" и ")}.
          </p>
          <Link to="/candidate/assessment" className="btn-primary shrink-0 !px-3.5 !py-1.5 text-xs">
            Подтвердить тестом →
          </Link>
        </div>
      )}
    </section>
  );
}
/** Короткая сводка для экрана результата теста. */
export function FeedbackSummary({ sessionId, fallbackLink = false }: { sessionId: string; fallbackLink?: boolean }) {
  const { data: fb, loading } = useApi<FeedbackData>(`/assessment/feedback?session_id=${sessionId}`, [sessionId]);
  if (loading) return null;
  // Ф6 (В2): один переход к карте роста на экране результата — из сводки или, если сводки нет, отдельной кнопкой
  if (!fb?.available) return fallbackLink ? <Link className="btn-ghost mt-4 inline-flex" to={`/candidate/feedback?session=${sessionId}`}>Карта навыков и маршрут роста</Link> : null;
  const s = fb.skill_map!.summary;
  // D3 п. 4: что востребовано у работодателей и ещё не подтверждено тестом — отдельной строкой от «слабее всего по тесту»
  const wanted = (fb.demand?.items ?? []).filter((x) => x.status !== "confirmed").slice(0, 3).map((x) => x.title);
  return (
    <section className="card mt-4">
      <h2 className="font-bold text-brand-night">Карта навыков и маршрут роста</h2>
      <p className="mt-1 text-sm text-brand-ink/70">
        Тем в тесте: {s.topics} · уверенно: {s.strong}{s.ok ? ` · в целом освоено: ${s.ok}` : ""} · пробелы: {s.gap}{s.pending ? ` · на проверке: ${s.pending}` : ""}.
        {s.best.length ? <> Сильнее всего: {s.best.join(", ")}.</> : null}
        {s.weakest.length ? <> {SOURCE_TEST}: {s.weakest.join(", ")}.</> : null}
      </p>
      {wanted.length > 0 && <p className="mt-1 text-sm text-brand-ink/70" data-testid="summary-demand">{SOURCE_DEMAND}: {wanted.join(", ")}.</p>}
      {fb.route && fb.route.length > 0 && (
        <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-sm text-brand-ink/75">{fb.route.slice(0, 3).map((r, i) => <li key={i}>{r.title}{stepSource(r) && <span className="text-brand-ink/60"> — {stepSource(r)!.toLowerCase()}</span>}</li>)}</ol>
      )}
      <Link className="btn-ghost mt-3 inline-flex" to={`/candidate/feedback?session=${sessionId}`}>Открыть карту навыков</Link>
    </section>
  );
}

export default function Feedback() {
  const [q] = useSearchParams();
  const sid = q.get("session");
  const { data: fb, error, loading } = useApi<FeedbackData>(`/assessment/feedback${sid ? `?session_id=${sid}` : ""}`, [sid]);
  if (loading && !fb) return <Loading />;
  if (error || !fb) return <Alert>{error}</Alert>;
  if (!fb.available) return (
    <div className="max-w-3xl"><PageTitle title="Карта навыков и рост" />
      <div className="mt-6"><Empty title="Карта навыков появится после теста" text={fb.message} action={<Link to="/candidate/assessment" className="btn-primary">Пройти тест</Link>} /></div></div>
  );
  const s = fb.session!;
  const sum = fb.skill_map!.summary;
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Карта навыков и рост"
        subtitle={`Тест ${s.direction_title} · ${s.grade_title}${s.finished_at ? ` от ${dt(s.finished_at).replace(/\.$/, "")}` : ""}. Только темы — без самих заданий и ключей. Работодатель этот разбор не видит.`} />
      <section className="grid gap-4 sm:grid-cols-4">
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Категория</p><p className="mt-2 text-lg font-bold text-brand-night">{catTitle(s.category_id)}</p>{s.confirmed != null && <p className="text-xs text-brand-ink/65">{s.confirmed ? "грейд подтверждён" : "грейд не подтверждён"}</p>}</div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Уверенно</p><p className="mt-2 text-xl font-bold text-brand-night">{sum.strong} из {sum.topics}</p><p className="text-xs text-brand-ink/65">тем теста</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Пробелы</p><p className="mt-2 text-xl font-bold text-brand-night">{sum.gap}</p><p className="text-xs text-brand-ink/65">{sum.weakest.length ? sum.weakest.join(", ") : "нет"}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Достоверность</p><p className="mt-2 text-lg font-bold text-brand-night">{s.integrity?.title ?? "—"}</p><p className="text-xs text-brand-ink/65">этот уровень видит работодатель</p></div>
      </section>
      {s.integrity && s.integrity.level !== "high" && (
        <Alert kind="info">Достоверность результата снижена. Общая причина: {s.integrity.reasons.join("; ").toLowerCase()}. {s.integrity.note ?? "Оценку уровня и грейд это не меняет."}</Alert>
      )}
      {fb.source === "facts" && <Alert kind="info">Подробной разбивки по заданиям для этого теста нет — карта построена по навыкам, подтверждённым тестом.</Alert>}
      <DemandGapBanner fb={fb} />
      <ThetaScale theta={s.theta} se={s.se} grade={s.claimed_grade} confirmed={s.confirmed} />
      {fb.route && fb.route.length > 0 && <Route steps={fb.route} />}
      <SkillMap fb={fb} />
      {fb.demand && <Demand d={fb.demand} />}
      {fb.market_hh && <HhMarketSkills m={fb.market_hh} />}
      {fb.competitions && fb.competitions.length > 0 && <Competitions list={fb.competitions} url={fb.fsp_calendar_url} />}
      <p className="text-xs text-brand-ink/65">Этот разбор входит и в ваш PDF-профиль (раздел <Link className="underline" to="/candidate/profile">«Профиль и резюме»</Link>). В версии профиля для работодателя его нет.</p>
    </div>
  );
}
