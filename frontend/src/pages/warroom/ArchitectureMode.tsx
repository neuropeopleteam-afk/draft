import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { launchLiveAvatar } from "../../components/Interview";
import { errText } from "../../components/ui";
import {
  ArchDiagram,
  EngineeringLevelMeter,
  MetricTile,
  nf,
} from "../../components/warroom/ArchDiagram";
import { FALLBACK_MEASURES, FALLBACK_SCENARIOS } from "../../components/warroom/fallbackData";
import type {
  EvaluateResult,
  MeasureSelection,
  MeasureSpec,
  ScenarioPublic,
  SimulateResult,
  Tone,
} from "../../components/warroom/types";
import { AvatarStage, type Voice } from "../../components/warroom/voice";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";

const SAMPLE_JUSTIFICATIONS: Record<string, string> = {
  payment:
    "Первопричина инцидента: синхронный вызов внешнего шлюза эквайринга внутри открытой транзакции БД исчерпывает пул соединений, а повторные запросы клиентов без ключа идемпотентности приводят к двойным списаниям. Для устранения атомарно фиксируем ключ идемпотентности в Redis через SET NX с TTL 24 часа, выносим вызов эквайринга под предохранитель breaker с коротким таймаутом 800 мс и включаем пул транзакций PgBouncer в рамках бюджета стоимости. При канареечной выкатке контролируем метрики задержки p99, долю ошибок 5xx и нулевое число двойных списаний по SLO.",
  kafka:
    "Первопричина сбоя: двойная запись в базу данных и брокер без общей транзакции приводит к потере событий при сетевых сбоях, а перебалансировка консюмеров без идемпотентности создаёт дубли заказов на складе. Применяем паттерн транзакционной таблицы outbox с пакетной выгрузкой batch и дедупликацию по ключу события через ON CONFLICT DO NOTHING. Контролируем разбор очереди, отставание лага консюмеров и сверку доставленных заказов по SLO.",
  k8s:
    "Первопричина каскадного отказа: выход процесса за предел памяти контейнера вызывает аварийные завершения OOM, отсутствие пробы готовности readiness направляет трафик в непрогретые узлы, а синхронные повторы без разброса добивают кластер. Задаём квоты limits.memory и долю кучи MaxRAMPercentage=70, включаем readinessProbe и экспоненциальные повторы со случайным разбросом jitter под предохранителем. Контролируем плавный rollout в рамках бюджета, p99 и отсутствие рестартов.",
  ai:
    "Первопричина уязвимости: прямая конкатенация системных инструкций и недоверенного текста ответа кандидата позволяет промпт-инъекции перехватить управление оценщиком и сжечь бюджет токенов. Вводим предварительный фильтр, изолируем данные разделителями и одноразовыми маркерами, требуем строгую JSON-схему с программной проверкой цитат, проверяем скрытую канарейку и ограничиваем max_tokens и бюджет сессии. Подозрительные ответы направляем эксперту на аудит и мониторинг квот.",
  frontend_ssr:
    "Первопричина деградации: хранение состояния запроса в глобальном сторе Node.js вызывает утечку памяти SSR, а одновременное истечение кэша каталога и повторные запросы при гидратации создают пробой кэша. Переходим на изолированный request-scoped стор, включаем кэширование swr с фоновым обновлением и склейкой coalesce параллельных запросов и сериализуем состояние для клиента. Контролируем потребление памяти воркеров в МБ и задержку p99 по SLO.",
  mobile_sync:
    "Первопричина шторма: одновременный выход мобильных устройств из офлайна с поштучной отправкой событий в цикле без разброса перегружает сеть и держит радиомодуль активным, разряжая батарею. Вводим случайный разброс jitter перед стартом синхронизации, агрегацию очереди в пачки batch с заголовком идемпотентности и соблюдение Retry-After при коде 429. Контролируем снижение числа фоновых пробуждений, p99 и отсутствие дублей очереди.",
  ml_drift:
    "Первопричина деградации: синхронные запросы в холодное хранилище признаков вызывают таймауты инференса, а рассинхронизация формул онлайн и офлайн витрин ведёт к дрейфу и пропуску фрода. Включаем потоковый прогрев горячего кэша признаков в Redis по единой спецификации, защищаем вызов предохранителем с коротким таймаутом и консервативным фолбэком по правилам. Контролируем задержку p99, индекс стабильности PSI и полноту детекции по SLO.",
  qa_flaky:
    "Первопричина паралича конвейера: параллельные воркеры автотестов мутируют общую базу данных без изоляции и зависят от нестабильной внешней песочницы, что вызывает гонки состояния и ложные падения flaky. Выделяем изолированную схему или вложенную транзакцию с откатом rollback на каждый worker_id и заменяем внешние вызовы детерминированным контрактным стабом. Отключаем слепые перезапуски, вводим карантин и мониторинг времени прохождения очереди.",
};

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

export default function ArchitectureMode({
  voice,
  scenarios = FALLBACK_SCENARIOS,
  measuresCatalog = FALLBACK_MEASURES,
  onScenarioUpdated,
}: {
  voice: Voice;
  scenarios?: ScenarioPublic[];
  measuresCatalog?: MeasureSpec[];
  onScenarioUpdated?: (scn: ScenarioPublic) => void;
}) {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialDir = searchParams.get("direction");

  const [sid, setSid] = useState<string>(() => {
    if (initialDir) {
      const found = scenarios.find((x) => x.direction === initialDir || x.id === initialDir);
      if (found) return found.id;
    }
    return scenarios[0]?.id ?? "payment";
  });

  const s = useMemo(() => scenarios.find((x) => x.id === sid) ?? scenarios[0], [scenarios, sid]);

  // Выбранные меры и их численные параметры: { measureId: { paramKey: number } }
  const [selectedMeasures, setSelectedMeasures] = useState<Record<string, Record<string, number>>>({});
  const [appliedMeasures, setAppliedMeasures] = useState<Record<string, Record<string, number>>>({});
  const [patchIdx, setPatchIdx] = useState<number>(1);
  const [code, setCode] = useState<string>(() => s.patches[1]?.code ?? "");
  const [justification, setJustification] = useState<string>("");
  const [phase, setPhase] = useState<"incident" | "deploying" | "applied">("incident");
  const [deployLog, setDeployLog] = useState<string[]>([]);
  const [simPreview, setSimPreview] = useState<SimulateResult | null>(null);
  const [evalResult, setEvalResult] = useState<EvaluateResult | null>(null);
  const [sec, setSec] = useState<number>(0);
  const [lostRub, setLostRub] = useState<number>(0);
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);

  const stagedIds = useMemo(() => new Set(Object.keys(selectedMeasures)), [selectedMeasures]);
  const liveIds = useMemo(() => new Set(Object.keys(appliedMeasures)), [appliedMeasures]);

  const buildMeasuresPayload = useCallback(
    (map: Record<string, Record<string, number>>): MeasureSelection[] =>
      Object.entries(map).map(([id, params]) => ({ id, params })),
    []
  );

  // Живой пересчёт симулятора через бэкенд при изменении мер, их параметров или кода
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      api<SimulateResult>("/warroom/simulate", {
        method: "POST",
        body: JSON.stringify({
          scenario_id: s.id,
          seed: s.seed,
          measures: buildMeasuresPayload(selectedMeasures),
          code_patch: code,
        }),
      })
        .then((res) => {
          if (active) setSimPreview(res);
        })
        .catch(() => {
          /* офлайн — остаются текущие значения */
        });
    }, 120);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [s.id, s.seed, selectedMeasures, code, buildMeasuresPayload]);

  // Секундомер инцидента и накопленные потери бизнеса до устранения сбоя
  useEffect(() => {
    const iv = window.setInterval(() => {
      setSec((x) => x + 1);
      setLostRub((x) => {
        const currentLoss =
          phase === "applied" && evalResult
            ? evalResult.metrics.loss_rub_sec
            : s.base.loss;
        return x + currentLoss;
      });
    }, 1000);
    return () => window.clearInterval(iv);
  }, [phase, evalResult, s.base.loss]);

  const selectScenario = (id: string) => {
    const next = scenarios.find((x) => x.id === id) ?? scenarios[0];
    setSid(id);
    setSelectedMeasures({});
    setAppliedMeasures({});
    setPatchIdx(1);
    setCode(next.patches[1]?.code ?? "");
    setJustification("");
    setPhase("incident");
    setDeployLog([]);
    setEvalResult(null);
    setSec(0);
    setLostRub(0);
    setErr(null);
    void voice.speak(
      `Инцидент «${next.title}». ${next.story} Выберите инженерные меры, настройте их параметры в рамках бюджета, исправьте патч кода и обоснуйте решение.`
    );
  };

  const regenerateSeedVariant = async () => {
    const nextSeed = ((s.seed + 373) % 8999) + 1000;
    try {
      const updated = await api<ScenarioPublic>(
        `/warroom/scenarios/${encodeURIComponent(s.id)}?seed=${nextSeed}`
      );
      onScenarioUpdated?.(updated);
      setPhase("incident");
      setEvalResult(null);
      setDeployLog([]);
    } catch (e) {
      setErr(errText(e));
    }
  };

  const toggleMeasure = (m: MeasureSpec) => {
    setSelectedMeasures((cur) => {
      const next = { ...cur };
      if (next[m.id]) {
        delete next[m.id];
      } else {
        const defaults: Record<string, number> = {};
        m.params.forEach((p) => {
          defaults[p.key] = p.default;
        });
        next[m.id] = defaults;
      }
      return next;
    });
  };

  const updateMeasureParam = (mid: string, key: string, val: number) => {
    setSelectedMeasures((cur) => ({
      ...cur,
      [mid]: {
        ...(cur[mid] ?? {}),
        [key]: val,
      },
    }));
  };

  const choosePatch = (idx: number) => {
    setPatchIdx(idx);
    setCode(s.patches[idx]?.code ?? "");
  };

  const fillOptimalDemo = () => {
    const opt: Record<string, Record<string, number>> = {};
    s.required.forEach((id) => {
      const spec = measuresCatalog.find((m) => m.id === id);
      const defaults: Record<string, number> = {};
      spec?.params.forEach((p) => {
        defaults[p.key] = p.default;
      });
      opt[id] = defaults;
    });
    setSelectedMeasures(opt);
    setPatchIdx(0);
    setCode(s.patches[0]?.code ?? "");
    setJustification(SAMPLE_JUSTIFICATIONS[s.id] ?? SAMPLE_JUSTIFICATIONS.payment);
  };

  const applyHotfix = async () => {
    if (phase === "deploying") return;
    setPhase("deploying");
    setEvalResult(null);
    setDeployLog([]);
    setErr(null);
    voice.stop();

    try {
      const res = await api<EvaluateResult>("/warroom/evaluate", {
        method: "POST",
        body: JSON.stringify({
          scenario_id: s.id,
          seed: s.seed,
          measures: buildMeasuresPayload(selectedMeasures),
          code_patch: code,
          justification,
          elapsed_s: Math.max(30, sec),
          save: true,
        }),
      });
      for (const line of res.feedback.deploy_log) {
        setDeployLog((l) => [...l, line]);
        await sleep(240);
      }
      setAppliedMeasures({ ...selectedMeasures });
      setEvalResult(res);
      setSimPreview(res);
      setPhase("applied");
      void voice.speak(res.voice_summary_ru);
    } catch (e) {
      setPhase("incident");
      setErr(errText(e));
    }
  };

  const goDefense = async () => {
    setBusy(true);
    setErr(null);
    try {
      voice.stop();
      await launchLiveAvatar(signIn, navigate, me?.role);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const activeResult = phase === "applied" && evalResult ? evalResult : simPreview;
  const shownMetrics =
    phase === "applied" && evalResult
      ? evalResult.metrics
      : {
          rps: Math.round(s.base.rps * (1 - s.base.err / 100)),
          incoming_rps: s.base.rps,
          p99_ms: s.base.p99_ms,
          error_rate_pct: s.base.err,
          loss_rub_sec: s.base.loss,
          extra_label: s.extra.label,
          extra_value: s.extra.base,
          extra_unit: s.extra.unit,
          mttr_s: 1440,
          cost_rub_month: simPreview?.metrics.cost_rub_month ?? s.base.base_cost_rub,
          base_cost_rub_month: s.base.base_cost_rub,
          measures_cost_rub_month: simPreview?.metrics.measures_cost_rub_month ?? 0,
          cost_budget_rub_month: s.slo.cost_budget_rub_month,
        };

  const tP99: Tone =
    shownMetrics.p99_ms > s.slo.p99_limit_ms * 3
      ? "bad"
      : shownMetrics.p99_ms > s.slo.p99_limit_ms
        ? "warn"
        : "ok";
  const tErr: Tone =
    shownMetrics.error_rate_pct > 5
      ? "bad"
      : shownMetrics.error_rate_pct > s.slo.error_limit_pct
        ? "warn"
        : "ok";
  const tLoss: Tone = shownMetrics.loss_rub_sec > 1000 ? "bad" : shownMetrics.loss_rub_sec > 0 ? "warn" : "ok";
  const tExtra: Tone =
    shownMetrics.extra_value > s.slo.extra_limit * 2 + 5
      ? "bad"
      : shownMetrics.extra_value > s.slo.extra_limit
        ? "warn"
        : "ok";
  const tCost: Tone =
    shownMetrics.cost_rub_month > s.slo.cost_budget_rub_month ? "bad" : "ok";

  const incidentOn = !(phase === "applied" && evalResult?.slo.slo_met);
  const currentChecks = simPreview?.code_checks ?? s.checks;
  const previewScore = simPreview?.scores.sim_score ?? 0;

  return (
    <div className="space-y-5" data-testid="wr-mode-arch">
      {/* Выбор одного из 8 боевых сценариев по направлениям */}
      <div
        className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4"
        role="radiogroup"
        aria-label="Боевой сценарий по направлению"
      >
        {scenarios.map((x, i) => (
          <button
            key={x.id}
            type="button"
            role="radio"
            aria-checked={x.id === sid}
            onClick={() => selectScenario(x.id)}
            data-testid={`wr-scn-${x.id}`}
            className={`group rounded-2xl border px-3.5 py-3 text-left transition-all ${
              x.id === sid
                ? "border-rose-400/75 bg-gradient-to-br from-rose-500/20 to-indigo-500/15 shadow-[0_0_28px_-10px_rgba(244,63,94,0.8)]"
                : "border-white/10 bg-white/[0.03] hover:border-white/30"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-rose-300">
                0{i + 1} · {x.direction_title.split("·")[0].trim()}
              </span>
              <span className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[9.5px] font-bold uppercase text-indigo-200">
                {x.target_grade}
              </span>
            </div>
            <p className="mt-1 text-sm font-extrabold leading-snug text-white">{x.title}</p>
            <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-white/60">{x.short}</p>
          </button>
        ))}
      </div>

      {/* Индивидуальный параметризованный вариант (защита от утечки) */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-indigo-400/25 bg-indigo-950/20 px-4 py-2.5">
        <div className="text-xs text-white/80">
          <span className="font-bold text-indigo-200">
            Параметризованный вариант #{s.seed}
          </span>{" "}
          · сервис <code className="font-mono text-white">{s.service}</code> (релиз{" "}
          <code className="font-mono text-white">{s.release}</code>) · входные числа нагрузки и бюджет
          генерируются индивидуально для защиты от утечки готовых ответов.
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={fillOptimalDemo}
            data-testid="wr-fill-optimal"
            className="rounded-lg border border-emerald-400/40 bg-emerald-500/15 px-3 py-1 text-xs font-bold text-emerald-200 hover:bg-emerald-500/25"
          >
            Подставить эталонное решение
          </button>
          <button
            type="button"
            onClick={() => void regenerateSeedVariant()}
            data-testid="wr-change-seed"
            className="rounded-lg border border-white/20 bg-white/5 px-3 py-1 text-xs font-semibold text-white/85 hover:bg-white/15"
          >
            Новый вариант чисел
          </button>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-4">
          {/* Живая схема микросервисов и 6 физических метрик (включая бюджет) */}
          <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0a0918]">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-2.5">
              <p className="flex items-center gap-2 text-sm font-bold text-white">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    incidentOn ? "animate-pulse bg-rose-500" : "bg-emerald-400"
                  }`}
                />
                {incidentOn ? `АВАРИЯ В ПРОДАКШНЕ · ${s.title}` : `ИНЦИДЕНТ УСТРАНЁН · ${s.title}`}
              </p>
              <p className="font-mono text-xs text-white/55">
                Время {String(Math.floor(sec / 60)).padStart(2, "0")}:{String(sec % 60).padStart(2, "0")} ·
                накопленный ущерб {nf(lostRub)} ₽
              </p>
            </div>
            <div className="px-2 pt-2">
              <ArchDiagram
                scenario={s}
                measuresCatalog={measuresCatalog}
                stagedIds={stagedIds}
                liveIds={liveIds}
                nodeTones={activeResult?.node_tones}
                applied={phase === "applied"}
                sloMet={!!evalResult?.slo.slo_met}
                score={evalResult?.total_score ?? previewScore}
              />
            </div>
            <div className="grid grid-cols-2 gap-2 p-3 md:grid-cols-3 xl:grid-cols-6" data-testid="wr-metrics">
              <MetricTile
                label="Успешный поток"
                value={nf(shownMetrics.rps)}
                unit="RPS"
                tone={shownMetrics.error_rate_pct > 5 ? "bad" : shownMetrics.error_rate_pct > 0.5 ? "warn" : "ok"}
                hint={`вход ${nf(s.base.rps)} RPS`}
              />
              <MetricTile
                label="Задержка p99"
                value={nf(shownMetrics.p99_ms)}
                unit="мс"
                tone={tP99}
                hint={`цель SLO ≤ ${nf(s.slo.p99_limit_ms)} мс`}
              />
              <MetricTile
                label="Ошибки 5xx"
                value={nf(shownMetrics.error_rate_pct, shownMetrics.error_rate_pct < 1 ? 2 : 1)}
                unit="%"
                tone={tErr}
                hint={`цель SLO ≤ ${nf(s.slo.error_limit_pct, 1)} %`}
              />
              <MetricTile
                label="Потери бизнеса"
                value={nf(shownMetrics.loss_rub_sec)}
                unit="₽/с"
                tone={tLoss}
                hint="прямой простой"
              />
              <MetricTile
                label={s.extra.label}
                value={nf(shownMetrics.extra_value)}
                unit={s.extra.unit}
                tone={tExtra}
                hint={`цель SLO ≤ ${nf(s.slo.extra_limit)}`}
              />
              <MetricTile
                label="Стоимость инфры"
                value={nf(shownMetrics.cost_rub_month)}
                unit="₽/мес"
                tone={tCost}
                hint={`бюджет ≤ ${nf(s.slo.cost_budget_rub_month)} ₽`}
              />
            </div>
          </div>

          {/* Пульт инженерных мер с численными параметрами + патч кода */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
                  1. Инженерные меры и численные параметры
                </p>
                <span className="font-mono text-[11px] text-indigo-200">
                  Выбрано: {stagedIds.size}
                </span>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-white/65">{s.story}</p>

              <div className="mt-3 space-y-2">
                {measuresCatalog.map((m) => {
                  const on = Boolean(selectedMeasures[m.id]);
                  const paramValues = selectedMeasures[m.id] ?? {};
                  return (
                    <div
                      key={m.id}
                      className={`rounded-xl border transition ${
                        on
                          ? m.trap
                            ? "border-amber-400/60 bg-amber-400/10"
                            : "border-emerald-400/60 bg-emerald-400/10"
                          : "border-white/10 bg-black/20 hover:border-white/25"
                      }`}
                    >
                      <button
                        type="button"
                        role="switch"
                        aria-checked={on}
                        onClick={() => toggleMeasure(m)}
                        data-testid={`wr-pat-${m.id}`}
                        className="flex w-full items-center gap-3 px-3 py-2 text-left"
                      >
                        <span
                          className={`relative h-5 w-9 shrink-0 rounded-full transition ${
                            on ? (m.trap ? "bg-amber-400" : "bg-emerald-400") : "bg-white/15"
                          }`}
                        >
                          <span
                            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                              on ? "left-[18px]" : "left-0.5"
                            }`}
                          />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-xs font-bold text-white">{m.label}</span>
                            <span className="shrink-0 font-mono text-[10px] text-white/55">
                              +{nf(m.base_cost_rub)} ₽/мес
                            </span>
                          </span>
                          <span className="mt-0.5 block text-[11px] leading-snug text-white/55">
                            {m.tech}
                          </span>
                        </span>
                      </button>

                      {/* Настраиваемые численные параметры включённой меры */}
                      {on && m.params.length > 0 && (
                        <div className="space-y-2 border-t border-white/10 bg-black/30 px-3 py-2.5">
                          {m.params.map((p) => {
                            const val = paramValues[p.key] ?? p.default;
                            const isOpt = val >= p.opt_min && val <= p.opt_max;
                            return (
                              <div key={p.key} className="space-y-1">
                                <div className="flex items-center justify-between text-[11px]">
                                  <label
                                    htmlFor={`param-${m.id}-${p.key}`}
                                    className="font-semibold text-white/85"
                                  >
                                    {p.label}
                                  </label>
                                  <span
                                    className={`font-mono font-bold ${
                                      isOpt ? "text-emerald-300" : "text-amber-300"
                                    }`}
                                  >
                                    {nf(val)} {p.unit}
                                  </span>
                                </div>
                                <input
                                  id={`param-${m.id}-${p.key}`}
                                  type="range"
                                  min={p.min}
                                  max={p.max}
                                  step={p.step}
                                  value={val}
                                  onChange={(e) =>
                                    updateMeasureParam(m.id, p.key, Number(e.target.value))
                                  }
                                  data-testid={`wr-param-${m.id}-${p.key}`}
                                  className="h-1.5 w-full cursor-pointer accent-emerald-400"
                                />
                                <p className="text-[10px] text-white/45">
                                  Рекомендуемый диапазон: {nf(p.opt_min)}–{nf(p.opt_max)} {p.unit}.{" "}
                                  {p.hint}
                                </p>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Правая колонка: патч кода + письменное обоснование */}
            <div className="flex min-w-0 flex-col gap-4">
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
                  2. Исправление кода (патч релиза)
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {s.patches.map((p, i) => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => choosePatch(i)}
                      data-testid={`wr-patch-${i}`}
                      className={`rounded-lg border px-2.5 py-1 text-[11px] font-semibold ${
                        patchIdx === i
                          ? "border-indigo-400 bg-indigo-500/20 text-white"
                          : "border-white/15 text-white/60 hover:text-white"
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <div className="mt-2 overflow-hidden rounded-xl border border-white/10 bg-[#05040c]">
                  <div className="flex items-center gap-1.5 border-b border-white/10 px-3 py-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-rose-500/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-amber-400/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
                    <span className="ml-2 font-mono text-[10px] text-white/45">
                      hotfix.{s.patches[patchIdx]?.lang ?? "py"}
                    </span>
                  </div>
                  <textarea
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    spellCheck={false}
                    aria-label="Патч кода хотфикса"
                    data-testid="wr-code"
                    className="block h-44 w-full resize-y bg-transparent p-3 font-mono text-[11.5px] leading-relaxed text-emerald-100/90 outline-none"
                  />
                </div>
                <ul className="mt-2 space-y-0.5 text-[11px]" aria-label="Проверка патча кода">
                  {currentChecks.map((c) => {
                    const ok = Boolean(c.passed);
                    return (
                      <li key={c.id} className={ok ? "text-emerald-300" : "text-rose-300"}>
                        {ok ? "✓" : "✗"} {c.label}
                      </li>
                    );
                  })}
                </ul>
              </div>

              {/* Письменное архитектурное обоснование (постмортем) */}
              <div className="flex-1 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
                    3. Письменное обоснование решения (рубрика с цитатами)
                  </p>
                  <button
                    type="button"
                    onClick={() =>
                      setJustification(SAMPLE_JUSTIFICATIONS[s.id] ?? SAMPLE_JUSTIFICATIONS.payment)
                    }
                    data-testid="wr-fill-justification"
                    className="text-[11px] font-bold text-indigo-300 hover:underline"
                  >
                    Заполнить пример обоснования
                  </button>
                </div>
                <p className="mt-1 text-[11px] text-white/55">
                  Опишите: (1) первопричину и узкое место, (2) почему выбраны эти меры и параметры с учётом
                  бюджета, (3) какие метрики SLO контролируете при выкатке.
                </p>
                <textarea
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  rows={4}
                  data-testid="wr-justification"
                  aria-label="Письменное инженерное обоснование"
                  placeholder="Первопричина инцидента: … Для устранения включаем … При выкатке контролируем p99, ошибки и бюджет по SLO…"
                  className="mt-2 w-full rounded-xl border border-white/10 bg-[#05040c] p-3 text-xs leading-relaxed text-white/90 outline-none focus:border-indigo-400"
                />

                {simPreview && simPreview.feedback.param_warnings.length > 0 && (
                  <div className="mt-2 rounded-xl border border-amber-400/30 bg-amber-500/10 p-2.5 text-[11px] text-amber-200">
                    {simPreview.feedback.param_warnings.map((w, idx) => (
                      <p key={idx}>• {w}</p>
                    ))}
                  </div>
                )}

                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-white/60">
                  <span>
                    Готовность симулятора:{" "}
                    <strong className="text-white">
                      {nf((simPreview?.scores.sim_score ?? 0) * 100)} %
                    </strong>{" "}
                    · код:{" "}
                    <strong className="text-white">
                      {nf((simPreview?.scores.code_score ?? 0) * 100)} %
                    </strong>
                  </span>
                  <span
                    className={
                      (simPreview?.metrics.cost_rub_month ?? s.base.base_cost_rub) <=
                      s.slo.cost_budget_rub_month
                        ? "text-emerald-300"
                        : "font-bold text-rose-300"
                    }
                  >
                    Бюджет: {nf(simPreview?.metrics.cost_rub_month ?? s.base.base_cost_rub)} /{" "}
                    {nf(s.slo.cost_budget_rub_month)} ₽/мес
                  </span>
                </div>

                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => void applyHotfix()}
                    disabled={phase === "deploying"}
                    data-testid="wr-apply"
                    className="flex-1 rounded-2xl bg-gradient-to-r from-rose-500 via-fuchsia-500 to-indigo-500 px-5 py-3.5 text-sm font-extrabold text-white shadow-[0_10px_40px_-10px_rgba(244,63,94,0.85)] transition hover:brightness-110 disabled:opacity-60"
                  >
                    {phase === "deploying"
                      ? "Проверка симулятором и рецензентом…"
                      : "Применить хотфикс в продакшн и оценить"}
                  </button>
                  <button
                    type="button"
                    onClick={() => selectScenario(s.id)}
                    className="rounded-xl border border-white/20 px-4 py-2.5 text-xs font-semibold text-white/80 hover:bg-white/10"
                  >
                    Сбросить
                  </button>
                </div>
              </div>
            </div>
          </div>

          {deployLog.length > 0 && (
            <pre
              className="overflow-x-auto rounded-xl border border-white/10 bg-black/60 p-3 font-mono text-[11.5px] leading-relaxed text-emerald-300/90"
              data-testid="wr-deploy-log"
              aria-live="polite"
            >
              {deployLog.map((l, i) => (
                <div key={i}>{l}</div>
              ))}
              {phase === "deploying" && <div className="animate-pulse">▍</div>}
            </pre>
          )}
        </div>

        {/* Правая панель: ИИ-архитектор, шкала инженерного уровня и разбор рубрики с цитатами */}
        <aside className="space-y-4">
          <div className="rounded-2xl border border-indigo-400/30 bg-gradient-to-b from-indigo-500/15 to-transparent p-4">
            <AvatarStage
              voice={voice}
              name="Настя · ИИ-архитектор"
              role="Рецензент архитектурных решений"
              size={168}
            />
          </div>

          <EngineeringLevelMeter
            score={evalResult?.total_score ?? previewScore}
            confirmedGrade={evalResult?.confirmed_grade ?? "middle"}
            targetGrade={s.target_grade}
            pending={phase === "deploying"}
          />

          {evalResult && (
            <div
              className={`rounded-2xl border p-4 ${
                evalResult.passed
                  ? "border-emerald-400/50 bg-emerald-400/10"
                  : "border-amber-400/40 bg-amber-400/10"
              }`}
              data-testid="wr-verdict"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-extrabold text-white">
                  {evalResult.passed
                    ? `Инцидент закрыт · уровень ${evalResult.confirmed_grade.toUpperCase()}`
                    : "Частичное решение · требуется доработка"}
                </p>
                <span className="rounded-lg bg-white/15 px-2 py-0.5 font-mono text-xs font-extrabold text-white">
                  {nf(evalResult.total_score * 100)} %
                </span>
              </div>

              <p className="mt-1.5 text-xs text-white/75">{evalResult.summary_ru}</p>
              <p className="mt-1 text-[11px] text-white/60">
                Симулятор: {nf(evalResult.scores.sim_score * 100)} % · Код:{" "}
                {nf(evalResult.scores.code_score * 100)} % · Рубрика обоснования:{" "}
                {nf(evalResult.rubric.rubric_score * 100)} %
              </p>

              {/* Разбор по рубрике с дословными цитатами */}
              <div className="mt-3 space-y-2 border-t border-white/10 pt-3" data-testid="wr-rubric">
                <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-200">
                  Разбор обоснования с проверкой дословных цитат:
                </p>
                <p className="text-[11px] text-white/75">{evalResult.rubric.comment_ru}</p>
                {evalResult.rubric.criteria.map((c) => (
                  <div
                    key={c.id}
                    className="rounded-lg border border-white/10 bg-black/30 p-2 text-[11px]"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-white">{c.title}</span>
                      <span
                        className={`font-mono font-bold ${
                          c.score >= 1
                            ? "text-emerald-300"
                            : c.score >= 0.5
                              ? "text-amber-200"
                              : "text-rose-300"
                        }`}
                      >
                        {nf(c.score * 100)} %
                      </span>
                    </div>
                    {c.quote ? (
                      <p className="mt-1 text-[10.5px] italic text-emerald-100/85">
                        Цитата: «{c.quote}»
                      </p>
                    ) : (
                      <p className="mt-1 text-[10px] text-white/45">
                        Дословная цитата по критерию в тексте не найдена
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-3 flex flex-col gap-2">
                <div
                  className="rounded-xl border border-emerald-400/30 bg-black/30 px-3 py-2 text-[11px] text-emerald-200"
                  data-testid="wr-save"
                >
                  <p className="font-bold">
                    {evalResult.saved_to_db
                      ? "Результат сохранён в профиле и засчитан в методику грейда"
                      : "Результат подписан криптографическим хешем SHA-256"}
                  </p>
                  <p className="mt-0.5 break-all font-mono text-[10px] text-emerald-200/75">
                    SHA-256: {evalResult.sha256_sig.slice(0, 32)}…
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void goDefense()}
                  disabled={busy}
                  className="rounded-xl border border-white/30 px-3 py-2.5 text-xs font-bold text-white hover:bg-white/10"
                  data-testid="wr-defense"
                >
                  {busy ? "Открываем комнату…" : "Перейти к 3-минутной устной защите решения"}
                </button>
              </div>
            </div>
          )}

          {err && (
            <p
              className="rounded-xl border border-rose-400/40 bg-rose-500/10 p-3 text-xs text-rose-200"
              role="alert"
            >
              {err}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
