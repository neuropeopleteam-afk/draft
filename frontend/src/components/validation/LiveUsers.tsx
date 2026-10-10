import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { fmtMin } from "../../lib/study";
import { NB, num, pct } from "../ui";

/** Блок /validation «Живые пользователи: жюри и посетители стенда». Показывается при N ≥ 3 завершённых путей (backend: app/modules/study,
 *  GET /api/study/summary); до этого сервер отдаёт shown=false и блок скрыт. Люди на демонстрационных данных; записи псевдонимизированы, наружу — только сводные числа. */

const ROLE: Record<string, string> = { candidate: "Кандидаты", employer: "Работодатели" };
const ci = (c?: number[] | null, f: (v: number) => string = (v) => num(v, 1)) => (c ? `${f(c[0])} … ${f(c[1])}` : "");

function T({ head, rows, caption, min = "30rem" }: { head: string[]; rows: ReactNode[][]; caption: string; min?: string }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full text-left text-sm" style={{ minWidth: min }}>
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-brand-night/5">{r.map((c, j) => <td key={j} className={`px-3 py-2 align-top tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function K({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card min-w-0">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-2xl font-extrabold tabular-nums text-brand-night">{value}</p>
      {hint && <p className="mt-1 text-xs text-brand-ink/65">{hint}</p>}
    </div>
  );
}

export default function LiveUsers({ data: d }: { data: any }) {
  if (!d?.shown) return null;
  const roles = Object.keys(d.n.by_role).filter((r) => d.n.by_role[r].enrolled > 0);
  const share = d.completion;
  const sus = d.sus;
  const susMin = d.sus_min_n ?? 5;  // n < 5 — балл SUS не результат (Я17)
  const p5 = d.p5;
  const steps = (ro: string) => d.step_titles?.[ro] ?? {};
  const stepKeys = (ro: string) => Object.keys(steps(ro));
  const stopped = Object.entries<number>(share.stopped_at ?? {});
  const err = d.errors;
  return (
    <section id="study-live" className="mt-12 scroll-mt-20" aria-labelledby="study-live-t">
      <h2 id="study-live-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Живые пользователи: жюри и посетители стенда</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-brand-ink/75" data-testid="study-signature">{d.signature}</p>
      <p className="mt-1 max-w-3xl text-xs leading-relaxed text-brand-ink/65">{d.world}</p>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        <K label="Завершили путь" value={d.n.done}
          hint={`из ${d.n.enrolled} начавших${roles.length ? ` · ${roles.map((r) => `${ROLE[r]?.toLowerCase()} ${d.n.by_role[r].done}`).join(", ")}` : ""}`} />
        <K label="Доля завершивших" value={pct(share.share?.share)}
          hint={share.share?.n ? `${share.share.k} из ${share.share.n} закончивших или бросивших${share.share.ci ? ` · ДИ 95 % ${ci(share.share.ci, (v) => pct(v))}` : ""}` : "ещё нет закончивших или бросивших"} />
        <K label="Медиана пути" value={d.time?.median_s != null ? `${fmtMin(d.time.median_s)}${NB}мин` : "—"}
          hint={d.time?.iqr_s ? `от начала сбора до конца пути · квартили ${fmtMin(d.time.iqr_s[0])} … ${fmtMin(d.time.iqr_s[1])}` : "от начала сбора до конца пути"} />
        <K label="SUS, 0–100" value={sus?.mean != null ? num(sus.mean, 1) : "—"}
          hint={sus?.mean != null ? `n = ${sus.n}${sus.ci ? ` · ДИ 95 % ${ci(sus.ci)}` : ""} · ориентир ${num(sus.benchmark ?? d.scale?.sus_benchmark, 0)}` : `пока недостаточно ответов (n = ${sus?.n ?? 0}), балл — от ${susMin} анкет`} />
      </div>

      <h3 className="mt-6 text-base font-bold text-brand-night">По ролям</h3>
      <div className="mt-2">
        <T caption="Прохождение и оценки по ролям" min="34rem" head={["Роль", "Начали", "Завершили", "Доля завершивших", "Медиана пути", "SUS"]}
          rows={roles.map((r) => {
            const c = share.by_role?.[r]; const t = d.time?.by_role?.[r]; const s = sus.by_role?.[r];
            const small = <span className="text-xs text-brand-ink/65">мало данных (меньше {d.min_n})</span>;
            return [ROLE[r], d.n.by_role[r].enrolled, d.n.by_role[r].done,
              c ? <>{pct(c.share?.share)}{c.share?.ci && <span className="block text-xs text-brand-ink/65">{ci(c.share.ci, (v) => pct(v))}</span>}</> : small,
              t?.median_s != null ? `${fmtMin(t.median_s)}${NB}мин` : small,
              s?.mean != null ? <>{num(s.mean, 1)}{s.ci && <span className="block text-xs text-brand-ink/65">{ci(s.ci)}</span>}</> : <span className="text-xs text-brand-ink/65">{s?.n ? `пока недостаточно ответов (n = ${s.n})` : `балл — от ${susMin} анкет`}</span>];
          })} />
      </div>

      <h3 className="mt-6 text-base font-bold text-brand-night">Время шагов и где бросают</h3>
      <p className="mt-1 text-sm text-brand-ink/70">Медиана по завершившим путь; шаг, уже пройденный к моменту включения сбора, не считается. «Бросили» — нет действий не менее 30 минут до конца пути.</p>
      <div className="mt-2 grid gap-3 md:grid-cols-2">
        {roles.map((r) => (
          <T key={r} caption={`Шаги пути: ${ROLE[r]}`} min="18rem" head={[ROLE[r], "Медиана", "Бросили"]}
            rows={stepKeys(r).map((k) => [steps(r)[k], d.time?.step_median_s?.[k] != null ? `${fmtMin(d.time.step_median_s[k])}${NB}мин` : "—", share.stopped_at?.[k] ?? 0])} />
        ))}
      </div>
      {stopped.length === 0 && <p className="mt-2 text-xs text-brand-ink/65">Бросивших путь пока нет.</p>}

      <h3 className="mt-6 text-base font-bold text-brand-night">Оценка подборки (P@5) и доверие к грейду</h3>
      <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        <K label="P@5 по оценкам людей" value={p5?.mean != null ? num(p5.mean, 2) : "—"}
          hint={p5?.mean != null ? `работодателей: ${p5.n}${p5.ci ? ` · ДИ 95 % ${ci(p5.ci, (v) => num(v, 2))}` : ""} · подходящими (4–5) признано ${p5.ratings_relevant} из ${p5.ratings}` : `оценили подборку: ${p5?.n ?? 0}, показываем от ${d.min_n}`} />
        {["candidate", "employer"].map((r) => {
          const b = d.belief?.[r];
          return <K key={r} label={r === "candidate" ? "Кандидаты: верят грейду" : "Работодатели: верят грейдам"} value={b?.mean != null ? num(b.mean, 2) : "—"}
            hint={b?.mean != null ? `шкала 1–5 · n = ${b.n}${b.ci ? ` · ДИ 95 % ${ci(b.ci, (v) => num(v, 2))}` : ""}` : `ответов: ${b?.n ?? 0}, показываем от ${d.min_n}`} />;
        })}
        <K label="Ошибки интерфейса" value={`${err?.participants ?? 0} из ${err?.of ?? 0}`}
          hint={`у скольких людей были ошибки · серверных: ${err?.server ?? 0}`} />
      </div>
      <p className="mt-2 text-xs text-brand-ink/65">SUS и P@5 дали только те, кто заполнил необязательную анкету; кандидаты в подборке демонстрационные, профили смоделированы. При малой выборке интервалы широкие: это и есть реальная неопределённость.</p>

      {Object.keys(d.blockers ?? {}).length > 0 && (
        <>
          <h3 className="mt-6 text-base font-bold text-brand-night">Что мешало</h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {Object.entries<number>(d.blockers).map(([t, n]) => <li key={t} className="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-brand-night ring-1 ring-brand-night/10">{t} <span className="tabular-nums text-brand-ink/65">· {n}</span></li>)}
          </ul>
        </>
      )}
      <p className="mt-4 text-xs text-brand-ink/65">Что собирается и как отключить: <Link to="/study" className="font-semibold text-brand-plum underline">статистика прохождения</Link>.</p>
    </section>
  );
}
