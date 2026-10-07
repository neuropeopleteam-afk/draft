import type { ReactNode } from "react";
import { Level, num, pct, range, ruText, signed, years } from "./ui";

const WF: Record<string, string> = { office: "Офис", hybrid: "Гибрид", remote: "Удалённо", any: "Любой формат" };

/** Обезличенная карточка кандидата: подтверждённые факты (T1/T2) отдельно от самоописания (T0). */
export function CandidateCard({ c, score, reasons, actions, compact = false }: {
  c: any; score?: number; reasons?: any[]; actions?: ReactNode; compact?: boolean;
}) {
  const t = c.test;
  const fsp = c.fsp ?? {};
  return (
    <article className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Кандидат {c.ref}</p>
          <p className="mt-1 text-lg font-bold text-brand-night">{c.category?.title ?? "Категория не присвоена"}</p>
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

      <div className={`mt-4 grid gap-3 ${compact ? "" : "md:grid-cols-2"}`}>
        <div className="rounded-xl bg-brand-blush/25 p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-brand-night"><Level level="T1" /> Тест</p>
          {t ? <p className="mt-1 text-brand-ink/75">{t.correct} из {t.answered} верно · θ = {signed(t.theta)} ± {num(t.se)}</p> : <p className="mt-1 text-brand-ink/65">нет результата</p>}
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
        </div>
      </div>

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
export function Integrity({ v, compact = false }: { v: { level: string; title: string; reasons: string[]; note?: string }; compact?: boolean }) {
  return (
    <div className={`mt-2 rounded-lg px-2.5 py-1.5 text-xs ring-1 ${INTEGRITY[v.level] ?? INTEGRITY.medium}`}>
      <p className="font-semibold">Достоверность результата: {v.title}</p>
      {!compact || v.level !== "high" ? (
        <ul className="mt-0.5 list-disc space-y-0.5 pl-4">{v.reasons.slice(0, compact ? 1 : 3).map((r, i) => <li key={i}>{r}</li>)}</ul>
      ) : null}
      {v.note && !compact && <p className="mt-0.5 opacity-80">{v.note}</p>}{/* версия для самого кандидата (Р27) */}
    </div>
  );
}
