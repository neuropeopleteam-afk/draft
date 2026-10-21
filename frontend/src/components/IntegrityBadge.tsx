// KF2: «Паспорт честности попытки (5 контуров)» — единая плашка для кандидата (своя попытка) и работодателя.
// Данные — GET /api/interview/defense/{id} (кандидат) и /api/interview/candidates/{ref} (работодатель): поле integrity
// (interview.service.integrity_passport) и рекомендация 3-минутной устной защиты с видеоаватаром (recommended, why).
// Р27: кандидату вне демо-режима механизмы не раскрываются — backend присылает detailed=false, и плашка показывает
// общие названия контуров без значений; жюри (демо-режим) и работодатель видят названия механизмов и значения.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { errText, useApi } from "./ui";

export type ContourStatus = "ok" | "warn" | "na" | "checked" | "recommended";
export type IntegrityPassport = {
  level?: string | null; title?: string | null; verdict: "clean" | "attention" | "recommended" | "confirmed" | "discrepancies";
  verdict_title: string; recommended: boolean; why?: string | null; detailed: boolean;
  honesty_index?: number | null; needs_followup_stage?: boolean; employer_reason_ru?: string | null;
  contours: { id: string; status: ContourStatus; value?: string | null }[];
};
type DefenseInfo = {
  enabled?: boolean; can_start?: boolean; minutes?: number; name_hint?: string; recommended?: boolean; why?: string | null;
  consent?: { version: string; items: string[] }; integrity?: IntegrityPassport | null;
  defense_status?: { status: string; title: string } | null;
};

/** Названия контуров: подробные — работодателю и жюри; общие — кандидату вне демо-режима (Р27). */
export const CONTOURS: Record<string, { n: number; detailed: string; general: string; plain?: string }> = {
  prior: { n: 1, detailed: "Канарейки и предзнание", general: "Самостоятельность знаний", plain: "контрольные задания и скорость чтения условия" },
  fit: { n: 2, detailed: "Психометрический индекс l_z (согласованность ответов)", general: "Согласованность ответов с уровнем", plain: "нет ли провала на простых вопросах при решении сложных" },
  origin: { n: 3, detailed: "Стеганографическая ИИ-метка (U+2063)", general: "Происхождение текста ответов", plain: "скрытая метка от копирования в ИИ и двойник при копировании условия" },
  screen: { n: 4, detailed: "Экран и клавиатурная биометрия (фокус, вставка, ритм, скриншоты)", general: "Поведение во время теста", plain: "уходы со вкладки, вставки из буфера, ритм набора" },
  live: { n: 5, detailed: "Камера / устная защита с видеоаватаром", general: "Камера / устная защита с видеоаватаром", plain: "проверка кадра по согласию и 3-минутная защита" },
};
const STATUS: Record<ContourStatus, { text: string; cls: string; mark: string }> = {
  ok: { text: "в норме", cls: "bg-emerald-50 text-emerald-800", mark: "✓" },
  warn: { text: "внимание", cls: "bg-amber-50 text-amber-900", mark: "!" },
  na: { text: "нет данных", cls: "bg-brand-night/5 text-brand-ink/70", mark: "·" },
  checked: { text: "проверено", cls: "bg-brand-night/5 text-brand-ink/80", mark: "·" },
  recommended: { text: "рекомендована", cls: "bg-brand-blush/40 text-brand-plum", mark: "→" },
};
const VERDICT_CLS: Record<IntegrityPassport["verdict"], string> = {
  clean: "bg-emerald-600 text-white", attention: "bg-amber-500 text-brand-night", recommended: "bg-brand-strong text-white",
  confirmed: "bg-emerald-700 text-white", discrepancies: "bg-amber-700 text-white",
};

/** Плашка по готовым данным паспорта. onDefense — кнопка «Пройти 3-минутную устную защиту» (только кандидату). */
export function IntegrityPassportView({ p, compact = false, minutes = 3, onDefense, busy, defenseStatus, consent }: {
  p: IntegrityPassport; compact?: boolean; minutes?: number; onDefense?: () => void; busy?: boolean;
  defenseStatus?: string | null; consent?: string[] | null;
}) {
  return (
    <section className={`rounded-2xl border border-brand-night/10 bg-white ${compact ? "p-3" : "p-4"} space-y-2`} aria-label="Паспорт честности попытки" data-testid="integrity-badge">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-bold text-brand-night">Паспорт честности попытки (5 контуров)</p>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${VERDICT_CLS[p.verdict]}`} data-testid="integrity-verdict">{p.verdict_title}</span>
      </div>
      {p.title && (
        <p className="text-xs text-brand-ink/70">
          Достоверность результата — {p.title}
          {typeof p.honesty_index === "number" ? ` (индекс самостоятельности ${Math.round(p.honesty_index * 100)} %)` : ""}. Оценку уровня и грейд пометка не меняет; при сомнениях назначается короткий дополнительный этап.
        </p>
      )}
      {p.detailed && p.employer_reason_ru && (
        <p className="rounded-xl bg-brand-night/[0.03] px-3 py-2 text-xs text-brand-ink/80" data-testid="integrity-employer-reason">
          {p.employer_reason_ru}
        </p>
      )}
      <ol className={`grid gap-1.5 ${compact ? "" : "sm:grid-cols-2"}`}>
        {p.contours.map((c) => {
          const meta = CONTOURS[c.id] ?? { n: 0, detailed: c.id, general: c.id };
          const st = STATUS[c.status] ?? STATUS.na;
          return (
            <li key={c.id} className="flex min-w-0 items-start gap-2 text-sm" data-testid={`integrity-contour-${c.id}`}>
              <span className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${st.cls}`} aria-hidden="true">{st.mark}</span>
              <span className="min-w-0">
                <span className="font-semibold text-brand-night">{meta.n}. {p.detailed ? meta.detailed : meta.general}</span>
                <span className="text-brand-ink/70"> — {c.id === "live" && c.status === "recommended" ? "устная защита рекомендована" : st.text}</span>
                {p.detailed && meta.plain && !compact && <span className="block text-[11px] text-brand-ink/55">{meta.plain}</span>}
                {p.detailed && c.value && <span className="block break-words text-xs text-brand-ink/65">{c.value}</span>}
                {!p.detailed && c.id === "live" && c.value && <span className="block break-words text-xs text-brand-ink/65">{c.value}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      {defenseStatus && <p className="text-sm font-semibold text-brand-night" data-testid="integrity-defense-status">{defenseStatus}</p>}
      {p.recommended && p.why && <p className="text-sm text-brand-ink/80" data-testid="integrity-why">{p.why}</p>}
      {p.recommended && onDefense && (
        <div className="space-y-1">
          <button className="btn-primary" disabled={busy} onClick={onDefense} data-testid="integrity-defense-start">
            {busy ? "Готовим вопросы…" : `Пройти ${minutes}-минутную устную защиту`}
          </button>
          {consent && consent.length > 0 && (
            <details className="text-xs text-brand-ink/65">
              <summary className="cursor-pointer">Нажимая кнопку, вы соглашаетесь на обработку ответов — условия</summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">{consent.map((t) => <li key={t}>{t}</li>)}</ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

/** Кандидат: паспорт своей попытки и кнопка устной защиты, если она рекомендована. */
export function IntegrityBadge({ sessionId, refId, direction, compact = false }: { sessionId?: string; refId?: string; direction?: string | null; compact?: boolean }) {
  const path = sessionId ? `/interview/defense/${sessionId}` : refId ? `/interview/candidates/${refId}${direction ? `?direction=${direction}` : ""}` : null;
  const { data } = useApi<DefenseInfo>(path, [path]);
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const p = data?.integrity;
  if (!p) return null;
  const canDefend = !!sessionId && !!data?.enabled && !!data?.can_start && p.recommended;
  async function start() {
    setBusy(true); setErr(null);
    try {
      const r = await api<{ id: string }>(`/interview/defense/${sessionId}`, { body: { name: data?.name_hint || "кандидат", consent: true } });
      navigate(`/candidate/interview/${r.id}?start=voice&autolisten=1`);  // живой разговор с видеоаватаром сразу голосом
    } catch (e) { setErr(e instanceof ApiError && e.status === 429 ? "Лимит живых запусков — попробуйте позже" : errText(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="space-y-1">
      <IntegrityPassportView p={p} compact={compact} minutes={data?.minutes ?? 3} busy={busy} onDefense={canDefend ? () => void start() : undefined}
        defenseStatus={refId ? data?.defense_status?.title ?? null : null} consent={data?.consent?.items ?? null} />
      {err && <p className="text-sm text-red-700" role="alert">{err}</p>}
    </div>
  );
}
