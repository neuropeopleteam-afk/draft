import { useEffect, useState, type ComponentType } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

// А2 → слот для А9 («Боевой ИИ-Полигон», components/warroom/WarRoomBadge.tsx).
// Подгружает компонент А9 через import.meta.glob без жёсткой сборочной зависимости до слияния веток.
const warroomModules = import.meta.glob<{ WarRoomBadge?: ComponentType<any>; default?: ComponentType<any> }>(
  "./warroom/WarRoomBadge.tsx"
);

const SENIOR_GRADES = new Set(["senior", "lead", "principal"]);

export function isSeniorPlusGrade(grade?: string | null): boolean {
  return !!grade && SENIOR_GRADES.has(grade.toLowerCase());
}

export function WarRoomSlot({
  mode,
  candidateRef,
  grade,
  direction,
  compact = false,
}: {
  mode: "candidate" | "employer";
  candidateRef?: string;
  grade?: string | null;
  direction?: string | null;
  compact?: boolean;
}) {
  const { me } = useAuth();
  const effMode: "candidate" | "employer" = me?.role === "candidate" ? "candidate" : mode;
  const [BadgeComp, setBadgeComp] = useState<ComponentType<any> | null>(null);
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    const loader = warroomModules["./warroom/WarRoomBadge.tsx"];
    if (loader) {
      loader()
        .then((mod) => {
          const C = mod.WarRoomBadge ?? mod.default;
          if (C) setBadgeComp(() => C);
        })
        .catch(() => {});
    }
  }, []);

  useEffect(() => {
    if (BadgeComp) return;
    if (effMode === "employer" && !candidateRef) return;
    if (effMode === "candidate" && !isSeniorPlusGrade(grade)) return;
    const path = effMode === "employer" ? `/warroom/candidates/${candidateRef}` : "/warroom/attempts/my";
    api<any>(path)
      .then((res) => setData(res))
      .catch(() => setData(null));
  }, [BadgeComp, effMode, candidateRef, grade]);

  if (effMode === "candidate" && !isSeniorPlusGrade(grade)) return null;
  if (effMode === "employer" && !candidateRef) return null;

  if (BadgeComp) {
    return (
      <div data-testid="warroom-badge-slot">
        <BadgeComp role={effMode} mode={effMode} candidateRef={candidateRef} refId={candidateRef} claimedGrade={grade} grade={grade} direction={direction} compact={compact} />
      </div>
    );
  }

  // Если компонент А9 ещё не влит, но кандидат уровня Senior+ — аккуратный блок «Боевой этап: разбор инцидента»
  if (!isSeniorPlusGrade(grade) && !data) return null;

  const items: any[] = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : data?.attempt ? [data.attempt] : [];
  const latest = items[0] ?? (data && typeof data === "object" && "verdict" in data ? data : null);

  if (effMode === "employer") {
    if (!latest && !isSeniorPlusGrade(grade)) return null;
    return (
      <div className="mt-3 rounded-xl border border-brand-night/10 bg-[#F7F6FB] p-3 text-xs" data-testid="warroom-badge-slot">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-semibold text-brand-night">Боевой этап: разбор инцидента (Senior+)</span>
          {latest ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-800">
              {latest.verdict_title ?? latest.status ?? "пройден"}
            </span>
          ) : (
            <span className="text-brand-ink/60">по запросу работодателя или добровольно</span>
          )}
        </div>
        {latest?.summary && <p className="mt-1 text-brand-ink/75">{latest.summary}</p>}
      </div>
    );
  }

  return (
    <section className="card space-y-2 border-brand/20 bg-gradient-to-r from-[#F7F6FB] to-white" data-testid="warroom-badge-slot">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand">Для уровней Senior и выше</p>
          <h3 className="text-base font-bold text-brand-night">Боевой этап: разбор инцидента</h3>
        </div>
        {latest ? (
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">
            {latest.verdict_title ?? latest.status ?? "пройден"}
          </span>
        ) : (
          <span className="chip">дополнительное доказательство навыка</span>
        )}
      </div>
      <p className="text-sm text-brand-ink/75">
        Практическая симуляция нештатной ситуации на продакшене: диагностика причин сбоя, архитектурное решение и план восстановления. Результат прикладывается к карточке для работодателей.
      </p>
      {latest?.summary && <p className="text-xs font-medium text-brand-night">{latest.summary}</p>}
      {data?.available_url && (
        <Link to={data.available_url} className="btn-ghost !py-1.5 text-xs">
          Перейти к разбору инцидента →
        </Link>
      )}
    </section>
  );
}
