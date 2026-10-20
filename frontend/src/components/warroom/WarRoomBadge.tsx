import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { nf } from "./ArchDiagram";

interface AttemptSummary {
  id: string;
  scenario_id: string;
  scenario_title: string;
  direction: string;
  direction_title: string;
  target_grade: string;
  confirmed_grade: string;
  slo_met: boolean;
  cost_rub_month: number;
  cost_budget_rub_month: number;
  sim_score: number;
  code_score: number;
  rubric_score: number;
  total_score: number;
  passed: boolean;
  reviewer_mode: string;
  rubric_details?: {
    comment_ru?: string;
    criteria?: { id: string; title: string; score: number; quote: string }[];
  };
  metrics?: {
    p99_ms?: number;
    error_rate_pct?: number;
    mttr_s?: number;
  };
  sha256_sig: string;
  created_at: string | null;
}

/** Блок «Боевой этап: разбор инцидента» для кабинета кандидата (Senior / Lead / Principal). */
export function CandidateWarRoomStage({
  direction,
  claimedGrade,
  className = "",
}: {
  direction?: string | null;
  claimedGrade?: string | null;
  className?: string;
}) {
  const [data, setData] = useState<{
    count: number;
    passed_count: number;
    attempts: AttemptSummary[];
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api<{ count: number; passed_count: number; attempts: AttemptSummary[] }>("/warroom/attempts/my")
      .then((res) => {
        if (alive) setData(res);
      })
      .catch(() => {
        if (alive) setData({ count: 0, passed_count: 0, attempts: [] });
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const best = data?.attempts?.[0];
  const dirQuery = direction ? `?direction=${encodeURIComponent(direction)}` : "";

  return (
    <section
      className={`rounded-2xl border border-indigo-500/25 bg-gradient-to-br from-indigo-950/40 via-[#120f24] to-rose-950/30 p-4 text-white ${className}`}
      data-testid="wr-candidate-stage"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-500/20 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-indigo-200">
            Боевой этап · Senior / Lead / Principal
          </span>
          <h3 className="mt-1.5 text-base font-extrabold text-white">
            Практический разбор архитектурного инцидента
          </h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-white/70">
            Для подтверждения старших грейдов{claimedGrade ? ` (${claimedGrade.toUpperCase()})` : ""} дополните тест
            решением реального сбоя под нагрузкой: настройте инженерные меры в рамках бюджета, исправьте код и защитите
            архитектурное решение.
          </p>
        </div>
        <Link
          to={`/warroom${dirQuery}`}
          className="shrink-0 rounded-xl bg-indigo-500 px-4 py-2 text-xs font-bold text-white shadow hover:bg-indigo-400"
          data-testid="wr-go-stage"
        >
          {best ? "Пройти ещё один инцидент" : "Открыть Боевой полигон"}
        </Link>
      </div>

      {!loading && best && (
        <div className="mt-3 rounded-xl border border-white/10 bg-black/30 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-bold text-white">
                {best.scenario_title} · <span className="text-indigo-200">{best.direction_title}</span>
              </p>
              <p className="mt-0.5 text-[11px] text-white/65">
                Балл: <strong className="text-white">{nf(best.total_score * 100)} %</strong> · Уровень:{" "}
                <strong className="text-emerald-300">{best.confirmed_grade.toUpperCase()}</strong> · SLO:{" "}
                <span className={best.slo_met ? "text-emerald-300" : "text-amber-300"}>
                  {best.slo_met ? "выполнены в бюджете" : "частично"}
                </span>{" "}
                · Стоимость: {nf(best.cost_rub_month)} / {nf(best.cost_budget_rub_month)} ₽/мес
              </p>
            </div>
            <span
              className={`rounded-lg px-2.5 py-1 text-[11px] font-bold ${
                best.passed ? "bg-emerald-500/20 text-emerald-200" : "bg-amber-500/20 text-amber-200"
              }`}
            >
              {best.passed ? "Подтверждено" : "На доработке"}
            </span>
          </div>
          <p className="mt-1.5 font-mono text-[10px] text-white/45">
            Подпись SHA-256: {best.sha256_sig.slice(0, 24)}… · результат виден работодателям в карточке профиля
          </p>
        </div>
      )}
    </section>
  );
}

/** Карточка результата Боевого ИИ-Полигона кандидата для кабинета работодателя. */
export function EmployerCandidateWarRoomCard({
  candidateRef,
  className = "",
}: {
  candidateRef: string;
  className?: string;
}) {
  const [data, setData] = useState<{
    has_attempts: boolean;
    passed: boolean;
    best_attempt: AttemptSummary | null;
  } | null>(null);

  useEffect(() => {
    if (!candidateRef) return;
    let alive = true;
    api<{ has_attempts: boolean; passed: boolean; best_attempt: AttemptSummary | null }>(
      `/warroom/candidates/${encodeURIComponent(candidateRef)}`
    )
      .then((res) => {
        if (alive) setData(res);
      })
      .catch(() => {
        if (alive) setData(null);
      });
    return () => {
      alive = false;
    };
  }, [candidateRef]);

  if (!data || !data.has_attempts || !data.best_attempt) return null;
  const b = data.best_attempt;
  const quotes = (b.rubric_details?.criteria ?? []).filter((c) => c.quote);

  return (
    <div
      className={`rounded-xl border border-indigo-500/25 bg-indigo-950/20 p-3 text-xs ${className}`}
      data-testid="wr-employer-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-bold text-indigo-200">
          Боевой этап (разбор инцидента): {b.scenario_title}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
            b.passed ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-200"
          }`}
        >
          {b.passed ? `Подтверждён ${b.confirmed_grade.toUpperCase()}` : `Частично (${nf(b.total_score * 100)} %)`}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-white/70">
        Итоговый балл: <strong>{nf(b.total_score * 100)} %</strong> · SLO:{" "}
        {b.slo_met ? "выполнены" : "не выполнены"} · Инфраструктура: {nf(b.cost_rub_month)} из{" "}
        {nf(b.cost_budget_rub_month)} ₽/мес
        {b.metrics?.p99_ms ? ` · p99 = ${nf(b.metrics.p99_ms)} мс` : ""}
      </p>
      {quotes.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-white/10 pt-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
            Проверенные цитаты из обоснования кандидата:
          </p>
          {quotes.map((q) => (
            <p key={q.id} className="text-[11px] text-white/75">
              <span className="font-semibold text-indigo-200">{q.title}:</span> «{q.quote}»
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export default function WarRoomBadge(props: {
  role?: "candidate" | "employer";
  candidateRef?: string;
  direction?: string | null;
  claimedGrade?: string | null;
  className?: string;
}) {
  if (props.role === "employer" && props.candidateRef) {
    return <EmployerCandidateWarRoomCard candidateRef={props.candidateRef} className={props.className} />;
  }
  return (
    <CandidateWarRoomStage
      direction={props.direction}
      claimedGrade={props.claimedGrade}
      className={props.className}
    />
  );
}
