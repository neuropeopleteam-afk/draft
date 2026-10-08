import type { ReactNode } from "react";
import { GradeBadge, GradeStatusNote } from "./GradeStatus";
import { Level, num, pct, range, ruText, signed, years } from "./ui";
import { Specializations } from "./Specializations";

const WF: Record<string, string> = { office: "Офис", hybrid: "Гибрид", remote: "Удалённо", any: "Любой формат" };

/** Обезличенная карточка кандидата: подтверждённые факты (T1/T2) отдельно от самоописания (T0). */
/** Ф2: шапка «Не хватает обязательного: …» — обязательные навыки без подтверждения тестом (T1), до трёх названий. */
export function MustLine({ m }: { m?: { missing?: string[]; missing_more?: number; missing_total?: number; required_total?: number; tier?: number } | null }) {
  if (!m || !m.required_total) return null;
  if (!m.missing_total) return <p className="mt-1 text-sm font-semibold text-emerald-800">Всё обязательное подтверждено тестом: {m.required_total} из {m.required_total}</p>;
  const more = m.missing_more ? ` и ещё ${m.missing_more}` : "";
  return (
    <p className="mt-1 max-w-2xl text-sm font-semibold text-amber-900" title="Тест не подтвердил эти навыки (проверены ниже порога, только заявлены или не проверялись). Это не «не умеет» — можно проверить зондом. В подборке такие кандидаты идут ниже тех, у кого всё обязательное подтверждено.">
      Не хватает обязательного: {(m.missing ?? []).join(", ")}{more}
    </p>
  );
}

export function CandidateCard({ c, score, reasons, actions, must, compact = false }: {
  c: any; score?: number; reasons?: any[]; actions?: ReactNode; must?: any; compact?: boolean;
}) {
  const t = c.test;
  const fsp = c.fsp ?? {};
  return (
    <article className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Кандидат {c.ref}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <p className="text-lg font-bold text-brand-night">{c.category?.title ?? (c.claimed?.title ? `Заявлено: ${c.claimed.title}` : "Категория не присвоена")}</p>
            <GradeBadge s={c.status} claimed={c.claimed} />
          </div>
          <MustLine m={must} />
          <GradeStatusNote s={c.status} className="mt-1 max-w-2xl" />
          {c.confirmed_by && <p className="mt-1 text-xs text-brand-ink/70">Грейд был предварительным и подтверждён {c.confirmed_by.title}{c.confirmed_by.ref_title ? ` («${c.confirmed_by.ref_title}»)` : ""}</p>}
          <p className="mt-0.5 text-sm text-brand-ink/65">
            {c.rank_in_category ? `Место ${c.rank_in_category} из ${c.category_size} в категории · ` : ""}
            {c.experience_years != null ? `стаж ${years(c.experience_years)} · ` : ""}
            {c.work_format ? WF[c.work_format] : ""}{c.city ? ` · ${c.city}` : ""}{c.relocation ? " · готов к переезду" : ""}
          </p>
        </div>
        {score != null && (
          <div className="text-right">
            <p className="text-2xl font-extrabold text-brand">{Math.round(score * 100)}</p>
            <p className="text-xs text-brand-ink/65">соответствие из 100</p>
          </div>
        )}
      </div>

      {c.specializations?.length > 1 && <div className="mt-4"><Specializations items={c.specializations} /></div>}
      <div className={`mt-4 grid gap-3 ${compact ? "" : "md:grid-cols-2"}`}>
        <div className="rounded-xl bg-brand-blush/25 p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-brand-night"><Level level="T1" /> Тест</p>
          {t ? <p className="mt-1 text-brand-ink/75">{t.correct} из {t.answered} верно · θ = {signed(t.theta)} ± {num(t.se)}</p>
            : c.status?.attempt?.theta != null ? <p className="mt-1 text-brand-ink/65">последняя попытка на {c.status.attempt.grade_title ?? c.status.attempt.grade}: θ = {signed(c.status.attempt.theta)} ± {num(c.status.attempt.se)} — грейд не подтверждён, в скор не входит</p>
            : <p className="mt-1 text-brand-ink/65">нет результата</p>}
          {c.provisional && <p className="mt-1 text-xs text-brand-ink/70">P(уровень не ниже Junior) = {c.provisional.p_pct} % · подтверждение от {c.provisional.confirm_pct} %, «не доказанно ниже» от {c.provisional.level_pct} %{c.provisional.attempts ? ` · дотестирований ${c.provisional.attempts} из ${c.provisional.attempts_max}` : ""}</p>}
          {t?.integrity && <Integrity v={t.integrity} compact={compact} />}
          {c.skills_confirmed?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.skills_confirmed.map((s: any) => <span key={s.tag} className="rounded-md bg-white px-2 py-0.5 text-xs font-semibold text-brand-night">{s.title} {pct(s.score)}</span>)}
            </div>
          )}
          {c.probes?.length > 0 && <p className="mt-2 text-xs text-brand-ink/70">Зонды: {c.probes.map((p: any) => `${p.title} — ${p.verdict}`).join("; ")}</p>}
        </div>
        <div className="rounded-xl bg-[#F3F2FB] p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-brand-night"><Level level={fsp.achievements?.length ? "T2" : "none"} /> Паспорт ФСП</p>
          {fsp.hidden ? <p className="mt-1 text-brand-ink/65">скрыто кандидатом</p>
            : fsp.achievements?.length ? (
              <ul className="mt-1 space-y-1 text-brand-ink/75">{fsp.achievements.slice(0, compact ? 2 : 4).map((a: any, i: number) => <li key={i}>{a.text}</li>)}</ul>
            ) : <p className="mt-1 text-brand-ink/65">истории ФСП нет — нейтрально</p>}
          {fsp.unverified_count > 0 && <p className="mt-1 text-xs text-brand-ink/65">Заявлено без подтверждения реестром: {fsp.unverified_count} — не учитывается</p>}
          {fsp.source === "demo" && <p className="mt-1 text-xs text-brand-lavender">демо-реестр</p>}
          {fsp.rating && !fsp.hidden && fsp.rating.competitions > 0 && <details className="mt-2 text-xs text-brand-ink/70">
            <summary className="cursor-pointer font-semibold text-brand-plum">Как считается ФСП: {num(fsp.rating.strength, 3)} · соревнований {num(fsp.rating.competitions, 0)}</summary>
            <p className="mt-2 leading-relaxed">{fsp.rating.policy}</p>
          </details>}
        </div>
      </div>
      {c.employment_safety?.minor && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
        <b>Особые условия оффера · {c.employment_safety.age_group === "16-17" ? "16–17 лет" : "14–15 лет"}.</b> {c.employment_safety.warning} {c.employment_safety.parental_consent ? "Отметка согласия есть." : "Отметки согласия пока нет."}
      </p>}

      {(c.stack_declared?.length > 0 || c.roles?.length > 0) && (
        <div className="mt-3 text-sm">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Заявлено кандидатом <Level level="T0" /></p>
          <p className="mt-1 text-brand-ink/70">{[...(c.stack_declared ?? []).map((s: any) => s.title), ...(c.roles ?? [])].join(", ")}</p>
        </div>
      )}

      {reasons && reasons.length > 0 && (
        <details className="mt-4 rounded-xl border border-brand-night/10 p-3" open>
          <summary className="cursor-pointer text-sm font-semibold text-brand-night">Почему в подборке</summary>
          <ul className="mt-2 space-y-1.5">
            {reasons.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <Level level={r.level} />
                <span><b className="font-semibold">{r.requirement}.</b> <span className="text-brand-ink/70">{ruText(r.text)}</span></span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        {c.market_range ? <p className="text-xs text-brand-ink/65">Рынок категории: {range(c.market_range.from, c.market_range.to)}</p> : <span />}
        {actions}
      </div>
    </article>
  );
}

const INTEGRITY: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  medium: "bg-amber-50 text-amber-900 ring-amber-200",
  low: "bg-brand-blush text-brand-plum ring-brand/30",
};

/** Достоверность результата теста (античит): уровень и причины — решение остаётся за человеком. */
export function Integrity({ v, compact = false }: { v: { level: string; title: string; reasons: string[] }; compact?: boolean }) {
  return (
    <div className={`mt-2 rounded-lg px-2.5 py-1.5 text-xs ring-1 ${INTEGRITY[v.level] ?? INTEGRITY.medium}`}>
      <p className="font-semibold">Достоверность результата: {v.title}</p>
      {!compact || v.level !== "high" ? (
        <ul className="mt-0.5 list-disc space-y-0.5 pl-4">{v.reasons.slice(0, compact ? 1 : 3).map((r, i) => <li key={i}>{r}</li>)}</ul>
      ) : null}
      {v.level !== "high" && <p className="mt-0.5 opacity-80">Не блокирует: на место в подборке не влияет, решение за вами — можно пригласить или проверить зондом.</p>}
    </div>
  );
}
