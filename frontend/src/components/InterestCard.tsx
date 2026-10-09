import { Link } from "react-router-dom";
import { Alert, Loading, NB, num, useApi } from "./ui";

/** Склонение по числу: plural(2, "работодатель", "работодателя", "работодателей"). */
export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? few : many;
}

const WEEKDAY = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function Delta({ now, before }: { now: number; before: number }) {
  if (!before && !now) return null;
  return <span className="text-xs text-brand-ink/65">на прошлой неделе: {num(before, 0)}</span>;
}

function Big({ value, label, hint, before, testid }: { value: number; label: string; hint?: string; before: number; testid: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-[#F3F2FB] p-4" data-testid={testid}>
      <p className="text-3xl font-bold tabular-nums text-brand-night">{num(value, 0)}</p>
      <p className="mt-1 text-sm font-semibold leading-snug text-brand-night">{label}</p>
      {hint && <p className="mt-1 text-xs leading-relaxed text-brand-ink/65">{hint}</p>}
      <p className="mt-1"><Delta now={value} before={before} /></p>
    </div>
  );
}

/** «За неделю карточку посмотрели N работодателей, вы были в M подборках, K зондов» — без названий компаний. */
export default function InterestCard() {
  const { data, loading, error } = useApi<any>("/me/interest");
  if (loading && !data) return <section className="card"><Loading /></section>;
  if (error || !data) return <Alert>{error || "Не удалось загрузить отметку интереса"}</Alert>;
  const d = data;
  const days: any[] = d.by_day ?? [];
  const max = Math.max(1, ...days.map((x) => x.views + x.selections));
  const none = d.employers_viewed + d.selections + d.probes === 0;
  return (
    <section className="card" data-testid="interest-card" aria-labelledby="interest-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="interest-title" className="text-lg font-bold text-brand-night">Интерес работодателей за 7 дней</h2>
        <span className="text-xs text-brand-ink/65">без названий компаний — только числа</span>
      </div>
      {!d.has_category ? (
        <div className="mt-4 rounded-xl bg-[#F3F2FB] p-4" data-testid="interest-empty">
          <p className="font-semibold text-brand-night">Пока считать нечего: у вас нет категории</p>
          <p className="mt-1 text-sm text-brand-ink/70">Работодатели находят кандидатов по категории из теста. Пройдите тест — после этого здесь появятся просмотры карточки, подборки и зонды.</p>
          <Link to="/candidate/assessment" className="btn-primary mt-3">Пройти тест</Link>
        </div>
      ) : (
        <>
          <p className="mt-2 text-sm leading-relaxed text-brand-ink/75" data-testid="interest-sentence">
            За неделю карточку посмотрели <b>{num(d.employers_viewed, 0)}{NB}{plural(d.employers_viewed, "работодатель", "работодателя", "работодателей")}</b>,
            {" "}вы были в <b>{num(d.selections, 0)}{NB}{plural(d.selections, "подборке", "подборках", "подборках")}</b>,
            {" "}вам прислали <b>{num(d.probes, 0)}{NB}{plural(d.probes, "зонд", "зонда", "зондов")}</b>.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Big testid="interest-employers" value={d.employers_viewed} label={`${plural(d.employers_viewed, "работодатель открыл", "работодателя открыли", "работодателей открыли")} вашу карточку`}
              hint="Считаются разные работодатели, повторный просмотр тем же — не в счёт" before={d.previous.employers_viewed} />
            <Big testid="interest-selections" value={d.selections} label={`${plural(d.selections, "подборка", "подборки", "подборок")} с вами в выдаче`}
              hint={d.best_rank ? `Лучшее место за неделю — ${num(d.best_rank, 0)}-е` : "Подборка — одна потребность работодателя"} before={d.previous.selections} />
            <Big testid="interest-probes" value={d.probes} label={`${plural(d.probes, "зонд", "зонда", "зондов")} — короткие задачи с вилкой`}
              hint="Зонд работодатель отправляет вам лично" before={d.previous.probes} />
          </div>
          {none && (
            <p className="mt-3 text-sm text-brand-ink/70" data-testid="interest-none">
              {d.visible_to_employers ? "За неделю никто не смотрел карточку — это нормально для начала: профиль появится в подборках, когда работодатель опишет подходящую потребность."
                : "Профиль скрыт от работодателей: дайте согласие на публикацию обезличенного профиля в настройках, чтобы вас могли найти."}
            </p>
          )}
          {!d.visible_to_employers && !none && <div className="mt-3"><Alert kind="info">Сейчас профиль скрыт от работодателей — числа за прошедшую неделю остаются, новые просмотры не появятся.</Alert></div>}
          <div className="mt-4" role="img" aria-label={`Просмотры карточки и попадания в подборки по дням: ${days.map((x) => `${x.date.slice(5)}: ${x.views + x.selections}`).join(", ")}`}>
            <div className="flex h-20 items-end gap-1.5 sm:gap-2">
              {days.map((x) => {
                const total = x.views + x.selections;
                return (
                  <div key={x.date} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${x.date}: просмотров ${x.views}, подборок ${x.selections}`}>
                    <div className="flex flex-col justify-end overflow-hidden rounded-t-md" style={{ height: `${Math.max(total ? 12 : 4, (total / max) * 100)}%` }}>
                      <div className="bg-brand-plum" style={{ flexGrow: x.selections }} />
                      <div className={total ? "bg-brand-strong" : "bg-brand-night/10"} style={{ flexGrow: Math.max(x.views, total ? 0 : 1) }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-1 flex gap-1.5 sm:gap-2">
              {days.map((x) => <span key={x.date} className="min-w-0 flex-1 text-center text-[11px] text-brand-ink/65">{WEEKDAY[new Date(x.date + "T12:00:00").getDay()]}</span>)}
            </div>
            <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-brand-ink/65">
              <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-brand-strong" /> открытия карточки</span>
              <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-brand-plum" /> попадания в подборки</span>
            </p>
          </div>
        </>
      )}
      {d.demo && <p className="mt-3 text-xs text-brand-ink/65" data-testid="interest-demo">Модельные данные: цифры демо-кандидата песочницы жюри посеяны заранее. Когда работодатель песочницы откроет вашу карточку, число работодателей вырастет на один.</p>}
      <p className="mt-3 text-xs leading-relaxed text-brand-ink/65">{d.note} <Link className="font-semibold text-brand hover:underline" to="/candidate/mydata">Мои данные</Link></p>
    </section>
  );
}
