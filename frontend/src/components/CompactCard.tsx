// Я10: компактная карточка подборки — решение «кого пригласить и почему» за несколько секунд.
// На виду: совпало (подтверждено тестом) / не проверено / риск / зарплата / «Пригласить» / «Сравнить»;
// доказательства (тест, ФСП, все причины, взаимный подбор) — по «Подробнее». Порядок и баллы не меняются.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { GradeBadge } from "./GradeStatus";
import { ScoreBox } from "./CandidateCard";
import { range } from "./ui";
import { FitBadge, type Fit } from "../pages/mutual/shared";

const SKILL = /^(Обязательно|Желательно): /;
const skillName = (r: any) => String(r.requirement).replace(SKILL, "");
const isMust = (r: any) => String(r.requirement).startsWith("Обязательно");

export interface CompactFacts { matched: string[]; unchecked: string[]; risks: string[]; salary: string | null; core: string | null; coreState?: string }

/** Короткие строки карточки из того же ответа подборки (reasons, must, card, core Я1, взаимный подбор). */
export function compactFacts(r: any, fit?: Fit | null): CompactFacts {
  const reasons: any[] = r.reasons ?? [];
  const c = r.card ?? {};
  const stack = reasons.filter((x) => SKILL.test(x.requirement ?? ""));
  const matched = stack.filter((x) => x.status === "confirmed").map((x) => skillName(x) + (isMust(x) ? "" : " (желательно)"));
  // по состоянию, обязательные первыми: «Go — только заявлен; Kubernetes, CI/CD — не проверялись»
  const label = (x: any) => skillName(x) + (isMust(x) ? "" : " (желательно)");
  const unchecked = (["declared", "missing"] as const).map((st) => {
    const xs = stack.filter((x) => x.status === st).sort((a, b) => Number(isMust(b)) - Number(isMust(a))).map(label);
    if (!xs.length) return null;
    const one = xs.length === 1;
    return `${xs.join(", ")} — ${st === "declared" ? (one ? "только заявлен" : "только заявлены") : (one ? "не проверялся" : "не проверялись")}`;
  }).filter((x): x is string => !!x);
  const risks: string[] = [];
  const req = r.must?.required_total ?? 0, miss = r.must?.missing_total ?? 0;
  if (miss > 0) risks.push(`не подтверждено тестом обязательных: ${miss} из ${req}`);  // «риск не виден» при 2 из 4 вводил бы в заблуждение
  const below = stack.filter((x) => x.status === "mismatch").map(skillName);
  if (below.length) risks.push(`ниже порога теста: ${below.join(", ")}`);
  const st = c.status?.status;
  if (st === "unconfirmed") risks.push("грейд не подтверждён тестом");
  else if (st === "provisional" || c.category?.preliminary) risks.push("грейд предварительный");
  else if (c.category?.ext_preliminary) risks.push(`${c.status?.grade_title ?? "Lead/Principal"} — предварительно`);  // Я25
  const grade = reasons.find((x) => x.requirement === "Специализация и грейд");
  const off = /грейд на (?:ступень|две ступени|три ступени) (?:выше|ниже) запрошенного/.exec(grade?.text ?? "");
  if (off) risks.push(off[0]);
  if (!c.test && st !== "unconfirmed") risks.push("нет результата теста");
  const integ = c.test?.integrity;
  if (integ && integ.level !== "high") risks.push(`достоверность теста: ${String(integ.title ?? "").toLowerCase()}`);
  for (const x of reasons) if ((x.requirement === "Формат работы" || x.requirement === "Город присутствия") && x.status === "mismatch") risks.push(String(x.text).toLowerCase());
  // FIX7 п. 10: стаж из потребности («3 года опыта») виден у каждого, кто его не набирает (T0, заявлено кандидатом)
  const expMin = r.exp_min;
  if (expMin != null && c.experience_years != null && Number(c.experience_years) < Number(expMin))
    risks.push(`стаж ${String(c.experience_years).replace(".", ",")} г. — меньше ${String(expMin).replace(".", ",")} из потребности`);
  if (fit && (fit.level === "low" || fit.decline_risk)) {
    const bad = (fit.factors ?? []).filter((f) => f.status === "bad").map((f) => f.title.toLowerCase());
    risks.push(`вероятно, откажет${bad.length ? `: ${bad.join(", ")}` : ""}`);
  }
  if (c.employment_safety?.minor) risks.push(`${c.employment_safety.age_group === "16-17" ? "16–17 лет" : "14–15 лет"}: особые условия оффера`);
  const sal = fit?.factors?.find((f) => f.key === "salary");
  const m = c.market_range;
  const market = m && (m.from || m.to) ? `рынок категории ${range(m.from, m.to)} на руки` : null;
  const salary = [sal?.text ? sal.text.replace(/^./, (s) => s.toLowerCase()) : null, market].filter(Boolean).join(" · ") || null;
  const k = r.core;  // Я1 (feat/key-lang): «Основной язык роли — Go: подтверждён тестом / заявлен / не заявлен»
  return { matched, unchecked, risks, salary, core: k?.headline ? String(k.headline) : null, coreState: k?.state };
}

function Line({ label, tone, children, testid }: { label: string; tone: string; children: ReactNode; testid: string }) {
  return (
    <li className="flex min-w-0 items-baseline gap-2" data-testid={testid}>
      <span className={`shrink-0 text-xs font-bold uppercase tracking-[0.08em] ${tone}`}>{label}</span>
      <span className="min-w-0 text-brand-ink/80">{children}</span>
    </li>
  );
}

/** Компактная карточка: шапка, 4–5 строк и действия; «Подробнее» раскрывает доказательства под карточкой. */
export function CompactCard({ r, rank, fit, picked, onPick, pickDisabled, onInvite, needId, badge, open, onToggle, details, side = false, active = false }: {
  r: any; rank: number; fit?: Fit | null; picked: boolean; onPick: () => void; pickDisabled?: boolean; onInvite: () => void;
  needId?: string; badge?: ReactNode; open: boolean; onToggle: () => void; details?: ReactNode;
  side?: boolean; active?: boolean;  // side — подробности в панели справа (широкий экран); active — эта карточка сейчас в ней
}) {
  const c = r.card ?? {};
  const f = compactFacts(r, fit);
  const coreTone = f.coreState === "confirmed" ? "text-emerald-800" : f.coreState === "absent" ? "text-amber-900" : "text-brand-ink/75";
  return (
    <article className={`card !p-4 sm:!p-5 ${active ? "ring-2 ring-brand/40" : ""}`} data-testid="candidate-card" data-compact="true" aria-label={`Кандидат ${r.ref}, место ${rank}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender"><span className="text-brand-ink/65">№{rank} · </span><span>Кандидат {r.ref}</span></p>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="font-bold text-brand-night">{c.category?.title ?? (c.claimed?.title ? `Заявлено: ${c.claimed.title}` : "Категория не присвоена")}</p>
            <GradeBadge s={c.status} claimed={c.claimed} />
            {c.model_note && <span className="chip bg-[#ECEAF8] text-brand-night" data-testid="model-note">{c.model_note}</span>}
            {badge}
          </div>
          {f.core && <p className={`mt-1 text-sm font-semibold ${coreTone}`} data-testid="compact-core">{f.core}</p>}
        </div>
        {r.score != null && <ScoreBox score={r.score} must={r.must} />}
      </div>
      <ul className="mt-2 space-y-1 text-sm" data-testid="compact-lines">
        <Line label="Совпало" tone="text-emerald-800" testid="compact-matched">{f.matched.length ? <>подтверждено тестом: {f.matched.join(", ")}</> : "тестом из требований ничего не подтверждено"}</Line>
        {f.unchecked.length > 0 && <Line label="Не проверено" tone="text-brand-ink/65" testid="compact-unchecked">{f.unchecked.join("; ")}<span className="hidden sm:inline"> — можно задать вопрос зондом</span></Line>}
        <Line label="Риск" tone="text-amber-900" testid="compact-risk">{f.risks.length ? f.risks.join("; ") : "по подтверждённым данным не виден"}</Line>
        {f.salary && <Line label="Зарплата" tone="text-brand-plum" testid="compact-salary">{f.salary}{fit && fit.level !== "low" ? <span className="ml-2 align-middle"><FitBadge fit={fit} short /></span> : null}</Line>}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className="btn-primary !px-4 !py-2" onClick={onInvite}>Пригласить</button>
        <label className={`inline-flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold ${picked ? "border-brand bg-brand-blush/50 text-brand-night" : "border-brand-night/15 text-brand-night"} ${pickDisabled && !picked ? "opacity-60" : ""}`}
          title={pickDisabled && !picked ? "Сравнить можно до трёх кандидатов" : "Отметьте 2–3 кандидатов и откройте сравнение"}>
          <input type="checkbox" className="accent-brand" checked={picked} disabled={pickDisabled && !picked} onChange={onPick} />Сравнить
        </label>
        <Link className="btn-ghost !px-3 !py-2" to={`/employer/candidates/${r.ref}?need=${needId ?? ""}`}>Открыть</Link>
        {side ? (
          <button type="button" className="ml-auto text-sm font-semibold text-brand hover:underline disabled:no-underline disabled:opacity-70" aria-pressed={active} disabled={active} onClick={onToggle}>
            {active ? "Подробности — справа" : "Подробнее справа: тест, ФСП, причины"}
          </button>
        ) : (
          <button type="button" className="ml-auto text-sm font-semibold text-brand hover:underline" aria-expanded={open} onClick={onToggle}>
            {open ? "Скрыть подробности" : "Подробнее: тест, ФСП, все причины"}
          </button>
        )}
      </div>
      {open && details && <div className="mt-3 border-t border-brand-night/10 pt-3" data-testid="compact-details">{details}</div>}
    </article>
  );
}
