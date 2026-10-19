// Н5: «Отборочный турнир ФСП под вакансию» — кубок компании × ФСП из потребности работодателя.
// Запуск (баннер в стиле ФСП), «Паспорт соревновательной задачи ФСП» с превью лидерборда и приглашением призёра
// в один клик. Призёры видны только псевдонимами; имя и контакты — после принятия приглашения, как во всём кубке.
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Status, errText } from "./ui";
import { salaryText } from "./Salary";
import { api } from "../lib/api";

export const isTournament = (c: any): boolean => !!c?.tournament;

/** Знак ФСП: та же плашка в баннере, паспорте, списках кубков и в кабинете федерации. */
export function FspMark({ light = false }: { light?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-[0.14em] ${light ? "bg-white/15 text-white" : "bg-brand-night text-white"}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-brand" aria-hidden="true" />ФСП
    </span>
  );
}

/** Баннер запуска на странице потребности и в «Кубке работодателя». Повторный клик по идущему турниру открывает его. */
export function TournamentLaunch({ needId, title, picker, className = "" }: { needId: string; title?: string; picker?: ReactNode; className?: string }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function launch() {
    setErr(null); setBusy(true);
    try {
      const cup = await api<any>(`/employer/cups/from-need/${needId}`, { body: {} });
      navigate(`/employer/cups/${cup.id}`);
    } catch (e) { setErr(errText(e)); setBusy(false); }
  }
  return (
    <section className={`relative overflow-hidden rounded-2xl bg-brand-night p-5 text-white sm:p-6 ${className}`} aria-labelledby={`fsp-launch-${needId}`}>
      <span className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-brand/25 blur-3xl" aria-hidden="true" />
      <span className="pointer-events-none absolute inset-y-0 left-0 w-1.5 bg-brand" aria-hidden="true" />
      <div className="relative flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0 max-w-xl">
          <div className="flex flex-wrap items-center gap-2">
            <FspMark light />
            <span className="text-xs font-semibold uppercase tracking-[0.12em] text-white/70">Кубок компании × ФСП · Продуктовое программирование</span>
          </div>
          <h2 id={`fsp-launch-${needId}`} className="mt-2 text-lg font-extrabold leading-snug sm:text-xl">
            {title ? `Отборочный турнир под «${title}»` : "Отборочный турнир под вакансию"}
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-white/80">
            Три задания банка с автопроверкой под обязательный стек потребности, 7 дней. Топ-5 призёров — прямой оффер с вилкой из потребности и очки в рейтинг ФСП.
          </p>
          {picker && <div className="mt-3">{picker}</div>}
        </div>
        <button type="button" className="btn-primary w-full whitespace-normal text-center sm:w-auto sm:shrink-0" disabled={busy} onClick={launch} data-testid="fsp-tournament-launch">
          {busy ? "Запускаем…" : "Запустить отборочный турнир ФСП под эту вакансию"}
        </button>
      </div>
      {err && <div className="relative mt-3"><Alert>{err}</Alert></div>}
    </section>
  );
}

const SOURCE: Record<string, string> = { need: "из потребности", market: "рынок категории — в потребности вилки нет" };

/** «Паспорт соревновательной задачи ФСП»: дисциплина, стек, задания, приз, превью лидерборда и приглашение призёра.
 *  Без таблиц и без ссылок на карточки — основная «Таблица результатов» кубка остаётся единственной таблицей. */
export function TournamentPassport({ cup, onInvite }: { cup: any; onInvite: (entryId: string) => Promise<void> }) {
  const t = cup.tournament;
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const top: any[] = (cup.leaderboard ?? []).filter((r: any) => r.position != null && r.position <= (t.top_n ?? 5)).slice(0, t.top_n ?? 5);
  const open = cup.status === "active";
  async function invite(id: string) {
    setBusy(id); setErr(null);
    try { await onInvite(id); } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }
  return (
    <section className="card space-y-5" aria-labelledby="fsp-passport">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><FspMark /><span className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{t.title}</span></div>
          <h2 id="fsp-passport" className="mt-2 text-lg font-bold text-brand-night">Паспорт соревновательной задачи ФСП</h2>
          <p className="mt-1 text-sm text-brand-ink/65">Отборочный турнир под потребность «{t.need_title}». Задания и автопроверка — из банка платформы ({t.bank_size} шаблонов), у каждого участника свой вариант.</p>
        </div>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-xl bg-[#F7F4FA] px-4 py-3">
          <dt className="text-xs font-semibold uppercase tracking-wide text-brand-ink/65">Дисциплина ФСП</dt>
          <dd className="mt-1 font-bold text-brand-night">{t.discipline}</dd>
          <dd className="mt-0.5 text-xs text-brand-ink/65">{t.category_title} · {t.tasks.length} задания · {cup.time_limit_min} мин на решение</dd>
        </div>
        <div className="rounded-xl bg-[#F7F4FA] px-4 py-3">
          <dt className="text-xs font-semibold uppercase tracking-wide text-brand-ink/65">Обязательный стек</dt>
          <dd className="mt-1.5 flex flex-wrap gap-1.5">
            {t.stack.map((s: string) => <span key={s} className="rounded-full bg-white px-2.5 py-0.5 text-xs font-semibold text-brand-night ring-1 ring-brand-night/10">{s}</span>)}
            {(t.stack_desired ?? []).map((s: string) => <span key={s} className="rounded-full border border-dashed border-brand-night/20 px-2.5 py-0.5 text-xs text-brand-ink/70">{s} · желательно</span>)}
          </dd>
        </div>
      </dl>
      <div>
        <h3 className="text-sm font-bold text-brand-night">Задания турнира</h3>
        <ol className="mt-2 grid gap-2 md:grid-cols-3">
          {t.tasks.map((x: any, i: number) => (
            <li key={x.family_id} className="rounded-xl border border-brand-night/10 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-lavender">Задание {i + 1} · {x.format_title}</p>
              <p className="mt-1 text-sm font-semibold leading-snug text-brand-night">{x.title}</p>
              <p className="mt-1.5 text-xs text-brand-ink/65">Проверяет: {(x.matched?.length ? x.matched : x.skills).join(", ")}</p>
            </li>
          ))}
        </ol>
      </div>
      <div className="rounded-xl border-l-4 border-brand bg-brand-blush/40 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-plum">Приз</p>
        <p className="mt-1 text-sm font-semibold leading-relaxed text-brand-night">{t.prize}</p>
        <p className="mt-1 text-xs text-brand-ink/70">{t.salary.source === "need" ? "Вилка — из потребности, та же уйдёт в приглашение." : `Вилка ${salaryText(t.salary.from, t.salary.to, t.salary.basis)} — ${SOURCE.market}.`} Места пишутся в паспорт ФСП призёра (уровень «платформа», T1) после итогов.</p>
      </div>
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-bold text-brand-night">Превью лидерборда · топ-{t.top_n}</h3>
          <span className="text-xs text-brand-ink/65">Полная таблица — выше</span>
        </div>
        {!top.length ? <p className="mt-2 text-sm text-brand-ink/65">Пока нет оценённых решений — призёры появятся после первых сдач.</p> : (
          <ul className="mt-2 divide-y divide-brand-night/5 rounded-xl border border-brand-night/10" data-testid="fsp-passport-top">
            {top.map((r) => (
              <li key={r.entry_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-extrabold ${r.position === 1 ? "bg-brand text-white" : "bg-brand-night/5 text-brand-night"}`}>{r.position}</span>
                <span className="min-w-0 flex-1 text-sm font-semibold text-brand-night">{r.full_name ?? r.alias}</span>
                <span className="text-sm tabular-nums text-brand-ink/80">{r.score_pct != null ? `${r.score_pct} %` : "—"}</span>
                {r.invited || r.invitation_status ? <Status s={r.invitation_status ?? "sent"} /> : open ? (
                  <button type="button" className="btn-ghost px-3 py-1.5 text-xs" disabled={busy !== null} onClick={() => invite(r.entry_id)}>
                    {busy === r.entry_id ? "Отправляем…" : "Пригласить призёра турнира в 1 клик"}
                  </button>
                ) : <span className="text-xs text-brand-ink/65">{r.invite_note ?? "—"}</span>}
              </li>
            ))}
          </ul>
        )}
        {err && <div className="mt-2"><Alert>{err}</Alert></div>}
        <p className="mt-2 text-xs text-brand-ink/65">Приглашение уходит сразу, с вилкой турнира и связью с потребностью; лимит — одно приглашение кандидату за 30 дней. Имя и контакты откроются, когда призёр примет приглашение.</p>
      </div>
    </section>
  );
}
