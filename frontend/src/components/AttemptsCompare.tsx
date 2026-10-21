import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { DIRECTION_TITLES, GRADE_TITLE_ALL, NB, dtt, num, pct, plainText, signed, useApi } from "./ui";
import { IntegrityBadge } from "./IntegrityBadge";  // KF2: паспорт честности попытки (5 контуров)

/** Две попытки теста рядом (И26): кандидату — /candidate/attempts, работодателю — в карточке кандидата.
 *  Данные — GET /api/assessment/attempts и /api/employer/candidates/{ref}/attempts (app/modules/assessment/attempts.py). */

export type Attempt = {
  id?: string; mode: string; mode_title: string; claimed_grade: string; finished_at: string | null;
  time_used_s: number | null; theta: number | null; se: number | null; correct: number | null; answered: number | null;
  accuracy: number | null; n_items: number; prior_items: number; status: string; status_title: string;
  grade_after: string | null; is_sandbox: boolean; engine: string;
};
export type Comparison = {
  first: Attempt; second: Attempt;
  overlap: { repeated_families: number; n_families_second: number; share_families: number | null; repeated_variants: number;
    n_variants_second: number; share_variants: number | null; same_subpool: boolean; engine: string };
  delta: { theta: number | null; se_diff: number | null; interval: number | null; within_error: boolean | null; se: number | null;
    accuracy: number | null; time_s: number | null; n_items: number; grade_changed: boolean; status_changed: boolean };
  changes: { id: string; title: string; text: string }[];
};

const STATUS_TONE: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-800", accepted_lower: "bg-sky-50 text-sky-800",
  provisional: "bg-amber-50 text-amber-900", unconfirmed: "bg-brand-night/5 text-brand-ink/80",
};

export const minutes = (s?: number | null) => (s == null ? "—" : s >= 600 ? `${Math.round(s / 60)}${NB}мин` : `${num(Math.round(s / 6) / 10, 1)}${NB}мин`);
const thetaSe = (a: Attempt) => (a.theta == null ? "—" : `${signed(a.theta)} ± ${num(a.se)}`);

function Status({ a }: { a: Attempt }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_TONE[a.status] ?? STATUS_TONE.unconfirmed}`}>
      {a.status_title}{a.grade_after ? ` · ${GRADE_TITLE_ALL[a.grade_after] ?? a.grade_after}` : ""}
    </span>
  );
}

function Row({ label, a, b, d }: { label: string; a: ReactNode; b: ReactNode; d?: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-brand-night/10 py-2 text-sm sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
      <div className="col-span-2 text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender sm:col-span-1 sm:text-sm sm:normal-case sm:tracking-normal sm:text-brand-ink/75">{label}</div>
      <div className="min-w-0 break-words text-brand-night">{a}</div>
      <div className="min-w-0 break-words text-brand-night">{b}</div>
      <div className="col-span-2 min-w-0 text-xs text-brand-ink/70 sm:col-span-1 sm:text-sm">{d}</div>
    </div>
  );
}

/** Таблица «Попытка 1 / Попытка 2 / разница» и список «что изменилось и почему». */
export function AttemptsCompare({ cmp, audience = "candidate", level = 3, refId, direction }: {
  cmp: Comparison; audience?: "candidate" | "employer"; level?: 2 | 3; refId?: string; direction?: string | null;
}) {
  const H = level === 2 ? "h2" : "h3";  // axe heading-order: на странице кандидата под h1 — h2, у работодателя под h2 — h3
  const { first: a, second: b, delta: d, overlap: o } = cmp;
  const head = (x: Attempt, n: number) => (
    <div className="min-w-0">
      <p className="font-bold text-brand-night">Попытка {n}</p>
      <p className="text-xs text-brand-ink/65">{dtt(x.finished_at)}</p>
      <p className="text-xs text-brand-ink/65">{GRADE_TITLE_ALL[x.claimed_grade] ?? x.claimed_grade} · {x.mode_title}{x.is_sandbox ? " · демо" : ""}</p>
    </div>
  );
  return (
    <div className="space-y-4">
      <div aria-label="Две попытки рядом">
        <div className="grid grid-cols-2 gap-x-3 pb-2 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
          <div className="hidden sm:block" />
          {head(a, 1)}{head(b, 2)}
          <p className="hidden text-sm font-bold text-brand-night sm:block">Разница</p>
        </div>
        <Row label="Оценка уровня ± точность" a={thetaSe(a)} b={thetaSe(b)}
          d={d.theta == null ? "—" : <>разница {signed(d.theta)}{d.interval != null && <> · {d.within_error ? "в пределах" : "больше"} точности ±{num(d.interval)}</>}</>} />
        <Row label="Точность оценки" a={num(a.se)} b={num(b.se)} d={d.se == null ? "—" : `${signed(d.se)} (${d.se < 0 ? "точнее" : d.se > 0 ? "менее точно" : "так же"})`} />
        <Row label="Доля верных ответов" a={a.accuracy == null ? "—" : `${pct(a.accuracy)} (${a.correct} из ${a.answered})`}
          b={b.accuracy == null ? "—" : `${pct(b.accuracy)} (${b.correct} из ${b.answered})`}
          d={d.accuracy == null ? "—" : `${signed(d.accuracy * 100, 0)}${NB}п. п.`} />
        <Row label="Грейд и статус" a={<Status a={a} />} b={<Status a={b} />} d={d.status_changed || d.grade_changed ? "изменился" : "без изменений"} />
        <Row label="Время" a={minutes(a.time_used_s)} b={minutes(b.time_used_s)} d={d.time_s == null ? "—" : `${d.time_s > 0 ? "+" : d.time_s < 0 ? "−" : ""}${minutes(Math.abs(d.time_s))}`} />
        <Row label="Оценённых заданий" a={a.n_items + a.prior_items} b={<>{b.n_items + b.prior_items}{b.prior_items ? ` (новых ${b.n_items})` : ""}</>}
          d={d.n_items ? signed(d.n_items, 0) : "—"} />
        <Row label="Повторы заданий во второй попытке" a="—"
          b={<>семейств {o.repeated_families} из {o.n_families_second}{o.share_families != null ? ` (${pct(o.share_families)})` : ""}; вариантов {o.repeated_variants} из {o.n_variants_second}</>}
          d={o.engine === "stub" ? "упрощённый режим теста" : o.repeated_families === 0 ? "параллельная форма" : "часть семейств повторилась"} />
      </div>
      {/* KF2: паспорт честности — кандидату по каждой попытке, работодателю — по попытке из карточки */}
      {audience === "candidate" && (a.id || b.id) && (
        <div className="grid gap-3 sm:grid-cols-2" aria-label="Честность попыток">
          {[a, b].map((x, n) => x.id ? (
            <div key={x.id} className="min-w-0 space-y-1">
              <p className="text-xs font-semibold text-brand-ink/70">Попытка {n + 1}</p>
              <IntegrityBadge sessionId={x.id} compact />
            </div>
          ) : null)}
        </div>
      )}
      {audience === "employer" && refId && <IntegrityBadge refId={refId} direction={direction} compact />}
      <section aria-label="Что изменилось и почему">
        <H className="font-bold text-brand-night">Что изменилось и почему</H>
        <ul className="mt-2 space-y-2 text-sm">
          {cmp.changes.map((x) => (
            <li key={x.id} className="border-l-2 border-brand-blush pl-3" title="Как устроено: сравнение оценок уровня и точности по шкале адаптивного теста">
              <p className="font-semibold text-brand-night">{plainText(x.title)}</p>
              <p className="text-brand-ink/75">{plainText(x.text)}</p>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-brand-ink/65">
          {audience === "employer"
            ? "Сравнение — по данным сессий теста (оценка уровня на общей шкале банка). Контрольные задания и тексты заданий не раскрываются. Кандидат может скрыть этот блок в настройках приватности."
            : "Контрольные задания в подсчёт повторов не входят и не раскрываются. Работодатель видит это сравнение в вашей карточке, если вы не скрыли его в настройках приватности."}
        </p>
      </section>
    </div>
  );
}

/** Блок в карточке кандидата у работодателя: виден, если попыток ≥ 2 и кандидат не скрыл сравнение. */
export function EmployerAttempts({ refId, direction }: { refId: string; direction?: string | null }) {
  const qs = direction ? `?direction=${direction}` : "";
  const { data } = useApi<any>(`/employer/candidates/${refId}/attempts${qs}`, [refId, direction]);
  if (!data) return null;
  if (!data.available) {
    return data.reason === "hidden_by_candidate"
      ? <p className="text-xs text-brand-ink/65">Сравнение попыток теста кандидат скрыл.</p> : null;
  }
  return (
    <section className="card space-y-3" aria-label="Две попытки теста рядом">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold text-brand-night">Две попытки теста рядом · {DIRECTION_TITLES[data.direction] ?? data.direction}</h2>
        <span className="text-xs text-brand-ink/65">Попыток в направлении: {data.n_attempts}; показаны две последние</span>
      </div>
      <AttemptsCompare cmp={data.comparison} audience="employer" refId={refId} direction={direction} />
    </section>
  );
}

/** Ссылка из истории тестов кандидата. */
export function AttemptsLink({ direction, n }: { direction: string; n: number }) {
  if (n < 2) return null;
  return <Link className="text-sm font-semibold text-brand" to={`/candidate/attempts?direction=${direction}`}>Сравнить две попытки</Link>;
}
