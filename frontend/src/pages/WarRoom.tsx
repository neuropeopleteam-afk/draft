// Боевой ИИ-Полигон Драфта (/warroom и /demo/warroom) — практический этап подтверждения старших грейдов
// (Senior / Lead / Principal) для кандидатов и интерактивная демонстрационная витрина для жюри.
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  FALLBACK_CONTOURS,
  FALLBACK_MEASURES,
  FALLBACK_SCENARIOS,
  FALLBACK_SIGNALS,
} from "../components/warroom/fallbackData";
import type {
  AntiCheatContourSpec,
  AntiCheatSignalSpec,
  MeasureSpec,
  ScenarioPublic,
} from "../components/warroom/types";
import { useArchitectVoice } from "../components/warroom/voice";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/meta";
import AntiCheatMode from "./warroom/AntiCheatMode";
import ArchitectureMode from "./warroom/ArchitectureMode";

function NavBtn({
  to,
  onClick,
  children,
  testid,
}: {
  to?: string;
  onClick?: () => void;
  children: ReactNode;
  testid?: string;
}) {
  const cls =
    "whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-semibold text-white/80 transition hover:bg-white/10 hover:text-white";
  return to ? (
    <Link to={to} className={cls} data-testid={testid}>
      {children}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls} data-testid={testid}>
      {children}
    </button>
  );
}

export default function WarRoom() {
  usePageTitle("Боевой ИИ-Полигон");
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { me, signOut } = useAuth();

  // Реальный боевой режим включается для вошедшего кандидата (не демо-учётки жюри) вне маршрута /demo
  const isJuryAccount = Boolean(
    me?.email && (me.email.toLowerCase().endsWith("@jury.example.com") || me.email.toLowerCase().startsWith("jury"))
  );
  const isCombatCandidate = Boolean(
    me &&
      me.role === "candidate" &&
      !isJuryAccount &&
      !location.pathname.startsWith("/demo") &&
      searchParams.get("demo") !== "1"
  );
  const demoMode = !isCombatCandidate;

  const [mode, setMode] = useState<"arch" | "cheat">(() =>
    typeof window !== "undefined" && window.location.hash === "#anticheat" ? "cheat" : "arch"
  );
  const voice = useArchitectVoice();
  const { stop } = voice;

  const [scenarios, setScenarios] = useState<ScenarioPublic[]>(FALLBACK_SCENARIOS);
  const [measures, setMeasures] = useState<MeasureSpec[]>(FALLBACK_MEASURES);
  const [contours, setContours] = useState<AntiCheatContourSpec[]>(FALLBACK_CONTOURS);
  const [signals, setSignals] = useState<AntiCheatSignalSpec[]>(FALLBACK_SIGNALS);

  useEffect(() => {
    let alive = true;
    api<{
      scenarios: ScenarioPublic[];
      measures: MeasureSpec[];
      anticheat_contours: AntiCheatContourSpec[];
      anticheat_signals: AntiCheatSignalSpec[];
    }>(`/warroom/scenarios?demo=${demoMode ? "true" : "false"}`)
      .then((res) => {
        if (!alive) return;
        if (res.scenarios?.length) setScenarios(res.scenarios);
        if (res.measures?.length) setMeasures(res.measures);
        if (res.anticheat_contours?.length) setContours(res.anticheat_contours);
        if (res.anticheat_signals?.length) setSignals(res.anticheat_signals);
      })
      .catch(() => {
        /* остаёмся на встроенном каталоге */
      });
    return () => {
      alive = false;
    };
  }, [demoMode]);

  const handleScenarioUpdated = (updated: ScenarioPublic) => {
    setScenarios((cur) => cur.map((x) => (x.id === updated.id ? updated : x)));
  };

  const switchMode = (m: "arch" | "cheat") => {
    stop();
    setMode(m);
    try {
      window.history.replaceState(null, "", m === "cheat" ? "#anticheat" : "#architecture");
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[#06050d] text-white">
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="absolute -left-40 -top-40 h-[520px] w-[520px] rounded-full bg-indigo-600/25 blur-[120px]" />
        <div className="absolute -right-40 top-40 h-[480px] w-[480px] rounded-full bg-rose-600/20 blur-[120px]" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:32px_32px]" />
      </div>

      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#06050d]/85 backdrop-blur-xl">
        <nav
          className="mx-auto flex max-w-[1400px] items-center gap-1 overflow-x-auto px-3 py-2 sm:px-6"
          aria-label="Навигация полигона"
        >
          <NavBtn onClick={() => navigate(-1)} testid="wr-nav-back">
            ← Назад
          </NavBtn>
          <span className="mx-1 h-5 w-px shrink-0 bg-white/15" />
          <NavBtn to="/" testid="wr-nav-home">
            На главную
          </NavBtn>
          <NavBtn to="/candidate" testid="wr-nav-candidate">
            Кабинет кандидата
          </NavBtn>
          {demoMode && (
            <>
              <NavBtn to="/employer" testid="wr-nav-employer">
                Кабинет работодателя
              </NavBtn>
              <NavBtn to="/expertise" testid="wr-nav-expertise">
                Экспертиза ФСП
              </NavBtn>
            </>
          )}
          <span className="ml-auto" />
          <span
            className={`hidden shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-widest md:flex ${
              isCombatCandidate
                ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-200"
                : "border-rose-400/40 bg-rose-500/10 text-rose-200"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 animate-pulse rounded-full ${
                isCombatCandidate ? "bg-emerald-400" : "bg-rose-400"
              }`}
            />
            {isCombatCandidate ? "боевой этап кандидата" : "демо-витрина полигона"}
          </span>
          {me && (
            <NavBtn
              onClick={() => {
                stop();
                signOut();
                navigate("/");
              }}
              testid="wr-nav-logout"
            >
              Выйти
            </NavBtn>
          )}
        </nav>
      </header>

      <main
        id="main"
        tabIndex={-1}
        className="relative mx-auto max-w-[1400px] px-3 pb-24 pt-5 outline-none sm:px-6"
      >
        <p className="font-mono text-[11px] font-bold uppercase tracking-[0.22em] text-indigo-300">
          {isCombatCandidate
            ? "Драфт · практический боевой этап кандидата (Senior · Lead · Principal)"
            : "Драфт · демонстрационная витрина архитектурного симулятора и контуров честности"}
        </p>
        <h1 className="mt-1 text-3xl font-black leading-tight tracking-tight md:text-4xl">
          Боевой ИИ-Полигон{" "}
          <span className="bg-gradient-to-r from-rose-400 via-fuchsia-400 to-indigo-400 bg-clip-text text-transparent">
            Драфта
          </span>
        </h1>
        <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/70">
          Старшие инженерные уровни нельзя измерить только выбором из вариантов. Восстановите
          работу системы под пиковой нагрузкой в рамках бюджета инфраструктуры и защитите решение
          письменным обоснованием с проверкой дословных цитат.
        </p>

        <div
          className="mt-4 grid gap-3 md:grid-cols-2"
          role="tablist"
          aria-label="Режим полигона"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === "arch"}
            onClick={() => switchMode("arch")}
            data-testid="wr-tab-arch"
            className={`rounded-2xl border px-5 py-3.5 text-left transition-all ${
              mode === "arch"
                ? "border-indigo-400/80 bg-gradient-to-br from-indigo-500/30 to-fuchsia-500/10 shadow-[0_0_50px_-15px_rgba(99,91,255,0.9)]"
                : "border-white/10 bg-white/[0.03] hover:border-white/30"
            }`}
          >
            <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-indigo-200">
              Режим А
            </span>
            <p className="mt-1 text-lg font-extrabold md:text-xl">
              Живой Архитектурный Полигон
            </p>
            <p className="mt-1 text-xs text-white/65">
              8 боевых инцидентов по направлениям · настройка численных параметров и бюджета ·
              рубрика с дословными цитатами
            </p>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "cheat"}
            onClick={() => switchMode("cheat")}
            data-testid="wr-tab-cheat"
            className={`rounded-2xl border px-5 py-3.5 text-left transition-all ${
              mode === "cheat"
                ? "border-rose-400/80 bg-gradient-to-br from-rose-500/30 to-cyan-500/10 shadow-[0_0_50px_-15px_rgba(244,63,94,0.9)]"
                : "border-white/10 bg-white/[0.03] hover:border-white/30"
            }`}
          >
            <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-rose-200">
              Режим Б · Демонстрационный стенд
            </span>
            <p className="mt-1 text-lg font-extrabold md:text-xl">
              Полигон Перехвата Нечестных Попыток
            </p>
            <p className="mt-1 text-xs text-white/65">
              Демонстрация на подготовленных примерах · фильтр оценщика, вариант-двойник и 5 контуров честности
            </p>
          </button>
        </div>

        <div className="mt-4">
          {mode === "arch" ? (
            <ArchitectureMode
              voice={voice}
              scenarios={scenarios}
              measuresCatalog={measures}
              demoMode={demoMode}
              onScenarioUpdated={handleScenarioUpdated}
            />
          ) : (
            <AntiCheatMode
              voice={voice}
              contours={contours}
              signals={signals}
              demoMode={demoMode}
            />
          )}
        </div>

        <p className="mt-10 text-center text-[11px] text-white/40">
          Расчёт метрик, бюджета, рубрики с цитатами и фильтрации текста выполняется на сервере
          (/api/warroom/*). В демонстрационном режиме попытки не сохраняются в профиль кандидата.
        </p>
      </main>
    </div>
  );
}
