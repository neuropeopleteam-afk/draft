import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { fmtPct, getLeakKVariants } from "../../lib/numbers";

interface CheatAttemptEntry {
  attempt_id: string;
  at: string;
  actor: string;
  claimed_grade: string;
  strategy: string;
  theta_est: number;
  verdict: string;
  verdict_title: string;
  canary_flagged: boolean;
  false_confirmed: boolean;
  note: string;
}

interface CheatChallengeData {
  demo_attempts_total: number;
  demo_false_confirmations: number;
  demo_caught_or_rejected: number;
  why_code_does_not_help: { id: string; title: string; detail: string }[];
  attempts: CheatAttemptEntry[];
  k_values?: Record<
    string,
    {
      k_published: number;
      n: number;
      fixed_bank: { leaked_share_of_test: number; theta_gain_mean: number; false_confirm_rate: number };
      parametric_bank: {
        theta_gain_mean: number;
        false_confirm_raw: number;
        false_confirm_protected: number;
        canary_caught_rate: number;
      };
    }
  >;
  claim_ru?: string;
  recompute?: string;
  code_ref?: string;
}

const STRATEGIES = [
  {
    id: "dump_lookup_1000",
    label: "Дамп K = 1 000 слитых вариантов + автопоиск",
    desc: "Скрипт мгновенно отвечает на варианты из опубликованной базы и угадывает остальные",
  },
  {
    id: "generator_source_analysis",
    label: "Анализ открытого Python/YAML-кода генераторов",
    desc: "Попытка восстановить ключ ответа по исходному коду шаблонов без знания серверного seed",
  },
  {
    id: "external_llm_copy",
    label: "Копирование текста заданий во внешнюю нейросеть",
    desc: "Передача условия задачи и кода во внешнюю LLM в обход блокировки буфера обмена",
  },
];

export default function CheatChallenge({ compact = false }: { compact?: boolean }) {
  const staticLeak = getLeakKVariants();
  const [data, setData] = useState<CheatChallengeData | null>(null);
  const [strategy, setStrategy] = useState<string>("dump_lookup_1000");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<CheatChallengeData>("/validation/cheat-challenge")
      .then(setData)
      .catch(() => {
        setData({
          demo_attempts_total: staticLeak.cheat_challenge?.demo_attempts_total ?? 3,
          demo_false_confirmations: staticLeak.cheat_challenge?.demo_false_confirmations ?? 0,
          demo_caught_or_rejected: staticLeak.cheat_challenge?.demo_caught_or_rejected ?? 3,
          why_code_does_not_help: staticLeak.why_code_does_not_help ?? [],
          attempts: [],
          k_values: staticLeak.k_values,
          claim_ru: staticLeak.claim_ru,
          recompute: staticLeak.recompute,
          code_ref: staticLeak.code_ref,
        });
      });
  }, [staticLeak]);

  const runAttempt = async () => {
    setBusy(true);
    try {
      const res = await api<{ latest: CheatAttemptEntry; summary: CheatChallengeData }>(
        "/validation/cheat-challenge/attempt",
        { method: "POST", body: { strategy, claimed_grade: "senior" } },
      );
      if (res?.summary) {
        setData((prev) => ({
          ...(prev ?? res.summary),
          ...res.summary,
          k_values: prev?.k_values ?? staticLeak.k_values,
        }));
      }
    } finally {
      setBusy(false);
    }
  };

  const kMap = (data?.k_values ?? staticLeak.k_values ?? {}) as NonNullable<CheatChallengeData["k_values"]>;
  const whyList = data?.why_code_does_not_help?.length
    ? data.why_code_does_not_help
    : staticLeak.why_code_does_not_help ?? [];
  const totalAttempts = data?.demo_attempts_total ?? staticLeak.cheat_challenge?.demo_attempts_total ?? 3;
  const falseConf = data?.demo_false_confirmations ?? staticLeak.cheat_challenge?.demo_false_confirmations ?? 0;

  return (
    <section
      id="cheat-challenge"
      data-testid="cheat-challenge-box"
      className="card border-brand-night/15 bg-gradient-to-br from-white via-brand-cream/35 to-white"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="chip-lime">Вызов жюри · «Обмани тест»</span>
          <h2 className="mt-2 font-display text-lg font-extrabold text-brand-night">
            Код генераторов банка открыт в репозитории — можно ли получить Senior, зная шаблоны и K слитых вариантов?
          </h2>
          <p className="mt-1 max-w-3xl text-xs text-brand-ink/75">
            Мы честно измерили выигрыш в баллах и вероятность ложного подтверждения Senior для кандидата уровня
            Junior/Middle (N = {staticLeak.n_per_k ?? 2000} попыток на каждое K ∈ {"{0, 10, 100, 1 000}"}) при знании
            исходного кода генераторов и базы опубликованных заданий.
          </p>
        </div>

        <div
          className="flex items-center gap-4 rounded-xl border border-brand-night/15 bg-brand-night px-4 py-3 text-white"
          data-testid="cheat-challenge-counters"
        >
          <div>
            <div className="text-[11px] uppercase tracking-wider text-white/65">Попыток взлома в демо</div>
            <div className="font-display text-2xl font-extrabold tabular-nums text-brand-lime">{totalAttempts}</div>
          </div>
          <div className="h-8 w-px bg-white/15" />
          <div>
            <div className="text-[11px] uppercase tracking-wider text-white/65">Ложных подтверждений Senior</div>
            <div className="font-display text-2xl font-extrabold tabular-nums text-white">{falseConf}</div>
          </div>
        </div>
      </div>

      {/* Сравнительная таблица K = 0, 10, 100, 1000 */}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-brand-night/10 text-[11px] uppercase tracking-wider text-brand-ink/60">
              <th className="py-2 pr-3">Известно вариантов K</th>
              <th className="py-2 pr-3">Фикс. банк (200 вопр.): доля слитых</th>
              <th className="py-2 pr-3">Фикс. банк: ложный Senior</th>
              <th className="py-2 pr-3">«Драфт» (1 504 сем. × 2,15·10⁹ зёрен): выигрыш Δθ</th>
              <th className="py-2 pr-3">«Драфт»: поймано канарейкой</th>
              <th className="py-2">«Драфт»: ложный Senior (с защитой)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-night/5 tabular-nums">
            {(["0", "10", "100", "1000"] as const).map((k) => {
              const row = kMap[k];
              if (!row) return null;
              return (
                <tr key={k}>
                  <td className="py-2 pr-3 font-bold text-brand-night">
                    K = {k === "0" ? "0 (честный проход)" : k}
                  </td>
                  <td className="py-2 pr-3 text-brand-ink/75">{fmtPct(row.fixed_bank.leaked_share_of_test, 0)}</td>
                  <td className="py-2 pr-3 font-semibold text-rose-700">
                    {fmtPct(row.fixed_bank.false_confirm_rate, 1)}
                  </td>
                  <td className="py-2 pr-3 text-brand-ink/75">
                    +{row.parametric_bank.theta_gain_mean.toFixed(2).replace(".", ",")} лог.
                  </td>
                  <td className="py-2 pr-3 text-brand-ink/75">
                    {k === "0" ? "—" : fmtPct(row.parametric_bank.canary_caught_rate, 1)}
                  </td>
                  <td className="py-2 font-bold text-emerald-700">
                    {fmtPct(row.parametric_bank.false_confirm_protected, 2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Интерактивный запуск демонстрационной попытки взлома */}
      <div className="mt-4 rounded-xl border border-brand-night/10 bg-white p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-bold text-brand-night">Испытать стратегию на уровне Senior:</span>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="rounded-lg border border-brand-night/15 bg-brand-cream/40 px-2.5 py-1.5 text-xs font-medium text-brand-night"
              data-testid="cheat-strategy-select"
            >
              {STRATEGIES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={runAttempt}
            disabled={busy}
            className="btn-primary px-3.5 py-1.5 text-xs"
            data-testid="cheat-run-btn"
          >
            {busy ? "Проверяем попытку…" : "Проверить попытку обмана"}
          </button>
        </div>

        {data?.attempts && data.attempts.length > 0 && (
          <div className="mt-3 space-y-1.5 border-t border-brand-night/10 pt-2.5 text-xs">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-ink/55">
              Последние попытки в журнале демо:
            </div>
            {data.attempts.slice(0, compact ? 2 : 4).map((a) => (
              <div
                key={a.attempt_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-brand-cream/40 px-3 py-1.5"
              >
                <div>
                  <span className="font-semibold text-brand-night">{a.actor}</span>
                  <span className="ml-2 text-brand-ink/70">{a.note}</span>
                </div>
                <span
                  className={`chip text-[11px] font-bold ${
                    a.verdict === "needs_followup"
                      ? "bg-amber-100 text-amber-900"
                      : "bg-brand-night/10 text-brand-night"
                  }`}
                >
                  Вердикт: {a.verdict_title} (θ = {a.theta_est.toFixed(2).replace(".", ",")})
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Короткое объяснение 3 причин, почему знание кода не помогает */}
      {!compact && whyList.length > 0 && (
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {whyList.map((w) => (
            <div key={w.id} className="rounded-xl border border-brand-night/10 bg-white p-3 text-xs">
              <div className="font-bold text-brand-night">{w.title}</div>
              <p className="mt-1 text-brand-ink/75">{w.detail}</p>
            </div>
          ))}
        </div>
      )}

      <p className="mt-3 text-[11px] text-brand-ink/55">
        Воспроизведение расчёта:{" "}
        <code className="rounded bg-brand-night/5 px-1.5 py-0.5">
          {data?.recompute ?? staticLeak.recompute ?? "cd backend && python -m app.modules.validation.leak_k_variants"}
        </code>{" "}
        · Код: <code>{data?.code_ref ?? staticLeak.code_ref}</code>
      </p>
    </section>
  );
}
