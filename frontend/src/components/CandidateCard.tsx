import { useEffect, useState, type ReactNode } from "react";
import { GradeBadge, GradeStatusNote } from "./GradeStatus";
import { Level, num, pct, ruText, signed, years } from "./ui";
import { Specializations } from "./Specializations";
import { MarketNote } from "./Salary";

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

/** Ф6 (Н5): навык проверен тестом или заданием, но порог не набран — не значок T1, а нейтральная пометка. */
export function ReasonLevel({ r }: { r: { level?: string | null; status?: string; weight?: number | null } }) {
  if (r.level === "T1" && r.status === "mismatch" && r.weight != null) {
    return <span title="Проверено тестом или заданием работодателя, порог подтверждения не набран — это не подтверждение навыка"
      className="inline-flex shrink-0 items-center rounded-md bg-gray-100 px-1.5 py-0.5 text-xs font-bold leading-none tracking-wide text-gray-600">не подтв.</span>;
  }
  return <Level level={r.level} />;
}

/** Ф6 (Н3): рядом с баллом — покрытие обязательного тестом; подсказка — что балл значит и какие условия жёсткие. */
export const SCORE_HINT = "Соответствие из 100 — взвешенная доля требований потребности, подтверждённых тестом (T1); обязательные весят больше желательных, ФСП и зонды добавляют немного. Заявленное кандидатом (T0) в балл не входит. Обязательные навыки — мягкое условие: без подтверждения кандидат не исключается, но помечен и идёт ниже. Формат и город — жёсткое условие: не прошедшие скрыты (можно показать всех).";

function ScoreBox({ score, must }: { score: number; must?: any }) {
  const req = must?.required_total ?? 0, miss = must?.missing_total ?? 0;
  return (
    <div className="text-right" title={SCORE_HINT}>
      <p className="text-2xl font-extrabold text-brand">{Math.round(score * 100)}</p>
      <p className="text-xs text-brand-ink/65">соответствие из 100</p>
      {req > 0 && <p data-testid="must-coverage" className={`mt-0.5 text-xs font-semibold ${miss ? "text-amber-900" : "text-emerald-800"}`}>обязательное: {req - miss} из {req}</p>}
    </div>
  );
}

/** Ф6 (Н9): короткая карточка подборки — 2–3 причины и пробелы; полная — по кнопке «Подробнее». */
function Brief({ c, reasons }: { c: any; reasons?: any[] }) {
  const stack = (reasons ?? []).filter((r) => /^(Обязательно|Желательно): /.test(r.requirement ?? ""));
  const name = (r: any) => String(r.requirement).replace(/^(Обязательно|Желательно): /, "");
  const okMust = stack.filter((r) => r.status === "confirmed" && r.requirement.startsWith("Обязательно")).map(name);
  const okWant = stack.filter((r) => r.status === "confirmed" && r.requirement.startsWith("Желательно")).map(name);
  const gaps = stack.filter((r) => r.status !== "confirmed" && r.requirement.startsWith("Обязательно"))
    .map((r) => `${name(r)} (${r.status === "mismatch" ? "ниже порога" : r.status === "declared" ? "только заявлено" : "не проверялось"})`);
  const t = c.test, fsp = c.fsp ?? {};
  const integ = t?.integrity && t.integrity.level !== "high" ? t.integrity.title : null;
  return (
    <ul className="mt-3 space-y-1 text-sm" data-testid="card-brief">
      <li className="flex items-start gap-2"><Level level={t ? "T1" : "none"} />
        <span className="text-brand-ink/80">{t ? `Тест: ${t.correct} из ${t.answered} верно · θ = ${signed(t.theta)} ± ${num(t.se)}${t.mode === "express" ? " · экспресс" : ""}${integ ? ` · достоверность: ${integ.toLowerCase()}` : ""}` : "Результата теста нет"}</span></li>
      {(okMust.length > 0 || okWant.length > 0) && <li className="flex items-start gap-2"><Level level="T1" />
        <span className="text-brand-ink/80">Подтверждено: {[...okMust, ...okWant.map((x) => `${x} (желательно)`)].join(", ")}</span></li>}
      {gaps.length > 0 && <li className="flex items-start gap-2"><Level level="none" />
        <span className="text-brand-ink/80">Пробелы обязательного: {gaps.join(", ")} — можно проверить зондом</span></li>}
      <li className="flex items-start gap-2"><Level level={fsp.achievements?.length && !fsp.hidden ? "T2" : "none"} />
        <span className="text-brand-ink/80">{fsp.hidden ? "Паспорт ФСП скрыт кандидатом" : fsp.achievements?.length ? `ФСП: ${fsp.achievements[0].text}${fsp.achievements.length > 1 ? ` и ещё ${fsp.achievements.length - 1}` : ""}` : "Истории ФСП нет — нейтрально"}</span></li>
    </ul>
  );
}

export function CandidateCard({ c, score, reasons, actions, must, compact = false, badge, mutual, collapsible = false, expanded = false }: {
  c: any; score?: number; reasons?: any[]; actions?: ReactNode; must?: any; compact?: boolean; badge?: ReactNode; mutual?: ReactNode;  // mutual — взаимный подбор (Н9)
  collapsible?: boolean; expanded?: boolean;  // Ф6 (Н9): короткая карточка с раскрытием по клику
}) {
  const t = c.test;
  const fsp = c.fsp ?? {};
  const [open, setOpen] = useState(!collapsible || expanded);
  useEffect(() => { setOpen(!collapsible || expanded); }, [collapsible, expanded]);
  const toggle = collapsible ? (
    <button type="button" className="text-sm font-semibold text-brand hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? "Свернуть" : "Подробнее: тест, навыки, ФСП, все причины"}
    </button>
  ) : null;
  if (!open) {
    return (
      <article className="card" data-testid="candidate-card" data-collapsed="true">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Кандидат {c.ref}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="text-lg font-bold text-brand-night">{c.category?.title ?? (c.claimed?.title ? `Заявлено: ${c.claimed.title}` : "Категория не присвоена")}</p>
              <GradeBadge s={c.status} claimed={c.claimed} />
              {badge}
            </div>
            <MustLine m={must} />
            <p className="mt-0.5 text-sm text-brand-ink/65">
              {c.rank_in_category ? `Место ${c.rank_in_category} из ${c.category_size} в категории · ` : ""}
              {c.experience_years != null ? `стаж ${years(c.experience_years)} · ` : ""}
              {c.work_format ? WF[c.work_format] : ""}{c.city ? ` · ${c.city}` : ""}{c.relocation ? " · готов к переезду" : ""}
            </p>
          </div>
          {score != null && <ScoreBox score={score} must={must} />}
        </div>
        <Brief c={c} reasons={reasons} />
        {c.employment_safety?.minor && <p className="mt-2 text-xs font-semibold text-amber-900">Особые условия оффера · {c.employment_safety.age_group === "16-17" ? "16–17 лет" : "14–15 лет"} — подробнее в карточке</p>}
        {mutual}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          {toggle}
          {actions}
        </div>
      </article>
    );
  }
  return (
    <article className="card" data-testid="candidate-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Кандидат {c.ref}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <p className="text-lg font-bold text-brand-night">{c.category?.title ?? (c.claimed?.title ? `Заявлено: ${c.claimed.title}` : "Категория не присвоена")}</p>
            <GradeBadge s={c.status} claimed={c.claimed} />
            {badge}
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
        {score != null && <ScoreBox score={score} must={must} />}
      </div>
      {mutual}

      {c.specializations?.length > 1 && <div className="mt-4"><Specializations items={c.specializations} /></div>}
      <div className={`mt-4 grid gap-3 ${compact ? "" : "md:grid-cols-2"}`}>
        <div className="rounded-xl bg-brand-blush/25 p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-brand-night"><Level level="T1" /> Тест</p>
          {t ? <p className="mt-1 text-brand-ink/75">{t.correct} из {t.answered} верно · θ = {signed(t.theta)} ± {num(t.se)}</p>
            : c.status?.attempt?.theta != null ? <p className="mt-1 text-brand-ink/65">последняя попытка на {c.status.attempt.grade_title ?? c.status.attempt.grade}: θ = {signed(c.status.attempt.theta)} ± {num(c.status.attempt.se)} — грейд не подтверждён, в скор не входит</p>
            : <p className="mt-1 text-brand-ink/65">нет результата</p>}
          {c.provisional && <p className="mt-1 text-xs text-brand-ink/70">P(уровень не ниже Junior) = {c.provisional.p_pct} % · подтверждение от {c.provisional.confirm_pct} %, «не доказанно ниже» от {c.provisional.level_pct} %{c.provisional.attempts ? ` · дотестирований ${c.provisional.attempts} из ${c.provisional.attempts_max}` : ""}</p>}
          {t && (t.mode === "express" || t.accepted_lower) && (
            <p className="mt-1 flex flex-wrap gap-1.5">
              {t.mode === "express" && <span className="chip" title="Экспресс-тест: 5–7 коротких заданий (за Senior — 8–12), интервал θ шире, чем у полного теста">экспресс-тест</span>}
              {t.accepted_lower && <span className="chip" title="Заявленный грейд не подтвердился; уровень ниже доказан тестом (P ≥ 80 %) и принят кандидатом">принят уровень ниже</span>}
            </p>
          )}
          {t?.integrity && <Integrity v={t.integrity} compact={compact} />}
          {c.skills_confirmed?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.skills_confirmed.map((s: any) => <span key={s.tag} className="rounded-md bg-white px-2 py-0.5 text-xs font-semibold text-brand-night">{s.title} {pct(s.score)}</span>)}
            </div>
          )}
          {c.freshness?.text && <p className="mt-1 text-xs text-brand-ink/70" title="Свежесть не входит в формулу подбора: показывает, насколько давно проверены навыки">Свежесть: {c.freshness.title.toLowerCase()}. {c.freshness.text}</p>}
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
                <ReasonLevel r={r} />
                <span><b className="font-semibold">{r.requirement}.</b> <span className="text-brand-ink/70">{ruText(r.text)}</span></span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        {c.market_range ? <MarketNote m={c.market_range} short /> : <span />}
        {actions}
      </div>
      {toggle && <div className="mt-3 border-t border-brand-night/5 pt-2">{toggle}</div>}
    </article>
  );
}

const INTEGRITY: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  medium: "bg-amber-50 text-amber-900 ring-amber-200",
  low: "bg-brand-blush text-brand-plum ring-brand/30",
};

/** Достоверность результата теста (античит): уровень и причины — решение остаётся за человеком. */
export function Integrity({ v, compact = false }: { v: { level: string; title: string; reasons: string[]; note?: string; camera?: { mode: string; title: string; remarks: string[]; notes: string[] } | null }; compact?: boolean }) {
  return (
    <div className={`mt-2 rounded-lg px-2.5 py-1.5 text-xs ring-1 ${INTEGRITY[v.level] ?? INTEGRITY.medium}`}>
      <p className="font-semibold">Достоверность результата: {v.title}</p>
      {!compact || v.level !== "high" ? (
        <ul className="mt-0.5 list-disc space-y-0.5 pl-4">{v.reasons.slice(0, compact ? 1 : 3).map((r, i) => <li key={i}>{r}</li>)}</ul>
      ) : null}
      {v.note && !compact && <p className="mt-0.5 opacity-80">{v.note}</p>}{/* версия для самого кандидата (Р27) */}
      {/* И16: итог камеры (по согласию кандидата) — только заголовок и до трёх замечаний; без камеры — нейтрально */}
      {v.camera && <p className="mt-0.5 text-[11px] opacity-90" data-testid="camera-title">{v.camera.title}{!compact && v.camera.remarks.length ? `: ${v.camera.remarks.join("; ")}` : ""}{!compact && v.camera.notes.length ? ` · ${v.camera.notes.join("; ")}` : ""}</p>}
      {v.level !== "high" && <p className="mt-0.5 opacity-80">Не блокирует: на место в подборке не влияет, решение за вами — можно пригласить или проверить зондом.</p>}
    </div>
  );
}
