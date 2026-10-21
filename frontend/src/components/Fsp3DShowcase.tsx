import { useEffect, useState } from "react";
import fspCrystalCore from "../assets/fsp-crystal-core.webp";
import fspCyberHead3d from "../assets/fsp-cyber-head-3d.webp";
import fspMedallion3d from "../assets/fsp-medallion-3d.webp";
import { getFspFacts, NUMBERS } from "../lib/numbers";

const fmtInt = (n: number): string => Number(n).toLocaleString("ru-RU");

const getRegionsCount = (): number => getFspFacts()?.regions ?? 89;
const getRegionsClaim = (): string =>
  getFspFacts()?.claim_ru ?? "89 действующих региональных представительств ФСП в России";

/** Строка ключевых показателей и правил под шапкой главной страницы (все цифры — из NUMBERS, статус — из /api/health). */
export function FspPulseBar() {
  const regions = getRegionsCount();
  const [healthOk, setHealthOk] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/health")
      .then((r) => {
        if (alive) setHealthOk(r.ok);
      })
      .catch(() => {
        if (alive) setHealthOk(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div
      className="fsp-pulse-bar"
      role="region"
      aria-label="Ключевые показатели и правила платформы"
      data-testid="fsp-pulse-bar"
    >
      <div className="mx-auto flex max-w-content flex-wrap items-center justify-between gap-x-6 gap-y-1.5 px-4 py-2 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11.5px] font-medium">
          {healthOk && (
            <span className="inline-flex items-center gap-2">
              <i className="fsp-pulse-dot" aria-hidden="true" />
              <strong className="font-mono font-bold tracking-wide text-white">Стенд работает</strong>
            </span>
          )}
          <span title={getRegionsClaim()}>
            <strong className="font-mono font-bold tracking-wide text-white">ФСП:</strong>{" "}
            <span className="text-[#DCE2FF]">{regions} региональных представительств</span>
          </span>
          <span className="hidden sm:inline">
            <strong className="font-mono font-bold tracking-wide text-white">Банк заданий:</strong>{" "}
            <span className="text-[#DCE2FF]">
              {NUMBERS.bank.directions} направлений · {fmtInt(NUMBERS.bank.families)} семейств задач
            </span>
          </span>
          <span className="hidden lg:inline">
            <strong className="font-mono font-bold tracking-wide text-white">Правило:</strong>{" "}
            <span className="text-[#DCE2FF]">приглашение — только с вилкой зарплаты</span>
          </span>
        </div>
        <a
          href="#fsp-ecosystem"
          className="hidden font-mono text-[11px] font-semibold text-[#A59DFF] transition hover:text-white md:inline"
        >
          Контур Федерации ФСП →
        </a>
      </div>
    </div>
  );
}

const HERO_STAGE_MODES = [
  {
    id: "cyber",
    label: "Кибер-атлет ФСП",
    src: fspCyberHead3d,
    alt: "3D-бюст кибер-атлета Федерации спортивного программирования с нейро-молекулярным графом вершин из титана, сапфирового стекла и рубинового ядра",
  },
  {
    id: "core",
    label: "Ядро верификации",
    src: fspCrystalCore,
    alt: "3D-скульптура ядра верификации ИТ-специалистов и достижений ФСП из титана, сапфирового стекла и рубинового ядра",
  },
  {
    id: "medallion",
    label: "Медальон грейда",
    src: fspMedallion3d,
    alt: "3D-медальон цифрового паспорта грейда и спортивных разрядов ФСП",
  },
] as const;

/** Фирменное созвездие узлов-вершин из официальной айдентики ФСП России (переход от алых вершин к индиго). */
function FspMolecularGraphSvg() {
  return (
    <svg
      viewBox="0 0 320 320"
      className="pointer-events-none absolute inset-0 m-auto h-[250px] w-[250px] opacity-65 sm:h-[310px] sm:w-[310px]"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="fsp-mol-edge" x1="40" y1="40" x2="280" y2="280" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#EC1D35" stopOpacity="0.72" />
          <stop offset="50%" stopColor="#8B80FF" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#402FFF" stopOpacity="0.82" />
        </linearGradient>
      </defs>
      <g stroke="url(#fsp-mol-edge)" strokeWidth="1.4" strokeLinecap="round">
        <line x1="160" y1="26" x2="94" y2="68" />
        <line x1="160" y1="26" x2="226" y2="68" />
        <line x1="94" y1="68" x2="54" y2="138" />
        <line x1="226" y1="68" x2="266" y2="138" />
        <line x1="54" y1="138" x2="88" y2="222" />
        <line x1="266" y1="138" x2="232" y2="222" />
        <line x1="94" y1="68" x2="226" y2="68" strokeDasharray="3 4" />
      </g>
      <circle cx="160" cy="26" r="5" fill="#402FFF" stroke="#E2E5FF" strokeWidth="1.5" />
      <circle cx="94" cy="68" r="4.5" fill="#EC1D35" stroke="#FFD6DC" strokeWidth="1.2" />
      <circle cx="226" cy="68" r="4.5" fill="#EC1D35" stroke="#FFD6DC" strokeWidth="1.2" />
      <circle cx="54" cy="138" r="4.5" fill="#685AFF" stroke="#E2E5FF" strokeWidth="1.2" />
      <circle cx="266" cy="138" r="4.5" fill="#685AFF" stroke="#E2E5FF" strokeWidth="1.2" />
      <circle cx="88" cy="222" r="3.5" fill="#402FFF" />
      <circle cx="232" cy="222" r="3.5" fill="#402FFF" />
    </svg>
  );
}

/** Правая 3D-сцена первого экрана главной страницы: фирменный 3D-образ кибер-атлета ФСП с нейро-молекулярным графом,
 *  переключатель ракурсов (Кибер-атлет ФСП / Ядро верификации / Медальон грейда) и 3 орбитальные капсулы. */
export function FspHeroMonolithStage({ mobile = false }: { mobile?: boolean }) {
  const [modeIdx, setModeIdx] = useState<number>(0);
  const par = { x: 0, y: 0 };
  const regions = getRegionsCount();
  const current = HERO_STAGE_MODES[modeIdx] ?? HERO_STAGE_MODES[0];
  const secondarySrc = current.id === "medallion" ? fspCrystalCore : fspMedallion3d;

  return (
    <div
      className="fsp-stage-card relative overflow-hidden rounded-3xl p-3.5 sm:p-5"
      data-testid={mobile ? "hero-fsp-showcase-mobile" : "hero-fsp-showcase"}
      aria-label="3D-символика и ядро верификации Федерации спортивного программирования"
    >
      {/* Верхняя панель переключения 3D-образов айдентики ФСП */}
      <div className="relative z-30 mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.08em] text-[#B8B2FF]">
          <span className="h-2 w-2 rounded-full bg-[#EC1D35]" aria-hidden="true" />
          Фирменный контур ФСП × Драфт
        </span>
        <div className="inline-flex rounded-xl border border-indigo-400/25 bg-[#0A0D22]/90 p-0.5" role="tablist" aria-label="3D-образы ФСП">
          {HERO_STAGE_MODES.map((m, idx) => {
            const on = idx === modeIdx;
            return (
              <button
                key={m.id}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => setModeIdx(idx)}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-bold transition ${
                  on
                    ? "bg-[#402FFF] text-white shadow-[0_4px_12px_-2px_rgba(64,47,255,0.85)]"
                    : "text-[#B8B2FF] hover:text-white"
                }`}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="fsp-hero-visual">
        <div className="fsp-core-glow" aria-hidden="true" />
        <div className="fsp-rings" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </div>
        <span className="fsp-core-shadow" aria-hidden="true" />
        <FspMolecularGraphSvg />

        {/* Парящий 3D-медальон грейда в левом верхнем углу сцены */}
        <div
          className="pointer-events-none absolute left-1.5 top-1.5 z-20 sm:left-2 sm:top-2"
          style={{
            transform: `translate3d(${-par.x * 0.6}px, ${-par.y * 0.6}px, 0)`,
            transition: "transform 0.45s cubic-bezier(0.16, 1, 0.3, 1)",
          }}
          aria-hidden="true"
        >
          <img
            src={secondarySrc}
            width={76}
            height={76}
            alt=""
            className="fsp-float-delayed h-[54px] w-[54px] object-contain drop-shadow-[0_14px_24px_rgba(64,47,255,0.65)] sm:h-[68px] sm:w-[68px]"
            decoding="async"
          />
        </div>

        {/* Центральная левитирующая 3D-скульптура «Кибер-атлет ФСП / Ядро Драфта» */}
        <div
          className="relative z-10 grid place-items-center py-1 sm:py-0"
          style={{
            transform: `translate3d(${par.x}px, ${par.y}px, 0)`,
            transition: "transform 0.45s cubic-bezier(0.16, 1, 0.3, 1)",
          }}
        >
          <span className="fsp-float">
            <img
              src={current.src}
              width={260}
              height={260}
              alt={current.alt}
              className="h-[178px] w-[178px] object-contain drop-shadow-[0_18px_36px_rgba(64,47,255,0.55)] sm:h-[242px] sm:w-[242px]"
              fetchPriority="high"
              decoding="async"
            />
          </span>
        </div>

        {/* Три парящие стеклянные орбитальные плашки (Orbit Pills) — на десктопе парят вокруг, на мобильном строятся компактным каскадом */}
        <div className="relative z-20 mt-2 grid w-full grid-cols-1 gap-1.5 sm:static sm:mt-0 sm:block">
          <a
            href="#fsp-ecosystem"
            className="fsp-orbit-pill fsp-orbit-pill--top"
            title={getRegionsClaim()}
          >
            <span className="fsp-orbit-pill__dot" aria-hidden="true" />
            <span>
              <b>ФСП: {regions} региональных представительств</b>
              <small>Спортивные разряды и кубки России</small>
            </span>
          </a>

          <a href="#candidates" className="fsp-orbit-pill fsp-orbit-pill--left">
            <span className="fsp-orbit-pill__dot fsp-orbit-pill__dot--red" aria-hidden="true" />
            <span>
              <b>Банк · {NUMBERS.bank.directions} ИТ-направлений</b>
              <small>{fmtInt(NUMBERS.bank.families)} семейств задач · устная защита</small>
            </span>
          </a>

          <a href="#employers" className="fsp-orbit-pill fsp-orbit-pill--bottom">
            <span className="fsp-orbit-pill__dot" aria-hidden="true" />
            <span>
              <b>Цифровой паспорт грейда</b>
              <small>Приглашение — только с вилкой зарплаты</small>
            </span>
          </a>
        </div>
      </div>
    </div>
  );
}

/** Крупный левитирующий 3D-медальон / 3D-кристалл с расходящимися кольцами для шапок Личных кабинетов. */
export function FspCabinet3DStage({
  kind = "medallion",
  badge,
  sub,
}: {
  kind?: "medallion" | "core";
  badge: string;
  sub?: string;
}) {
  const src = kind === "core" ? fspCrystalCore : fspMedallion3d;
  return (
    <div
      className="relative flex h-[118px] w-full shrink-0 items-center justify-center select-none sm:h-[164px] sm:w-[184px]"
      aria-hidden="true"
    >
      <div className="fsp-core-glow" />
      <div className="fsp-rings fsp-rings--sm">
        <i />
        <i />
        <i />
      </div>
      <span className="fsp-core-shadow" />
      <span className="fsp-float relative z-10">
        <img
          src={src}
          width={148}
          height={148}
          alt=""
          className="h-[104px] w-[104px] object-contain drop-shadow-[0_20px_32px_rgba(0,0,0,0.75)] sm:h-[142px] sm:w-[142px]"
          decoding="async"
        />
      </span>
      <span className="fsp-mini-orbit-pill z-20">
        <span className="fsp-orbit-pill__dot" />
        <span>
          <b>{badge}</b>
          {sub && <small>{sub}</small>}
        </span>
      </span>
    </div>
  );
}
