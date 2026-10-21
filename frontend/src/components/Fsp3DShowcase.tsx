import { useEffect, useState, type MouseEvent } from "react";
import fspCrystalCore from "../assets/fsp-crystal-core.webp";
import fspMedallion3d from "../assets/fsp-medallion-3d.webp";
import { fmtInt, NUMBERS } from "../lib/numbers";

const getRegionsCount = (): number => (NUMBERS as any)?.fsp_facts?.regions ?? 89;
const getRegionsClaim = (): string =>
  (NUMBERS as any)?.fsp_facts?.claim_ru ?? "89 действующих региональных представительств ФСП в России";

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

/** Правая 3D-сцена первого экрана главной страницы: левитирующий 3D-кристалл верификации ФСП,
 *  расходящиеся радиоволны, медальон грейда и 3 парящие стеклянные орбитальные капсулы с параллаксом. */
export function FspHeroMonolithStage() {
  const [par, setPar] = useState({ x: 0, y: 0 });
  const regions = getRegionsCount();

  function onMove(e: MouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const nx = ((e.clientX - r.left) / Math.max(1, r.width) - 0.5) * 18;
    const ny = ((e.clientY - r.top) / Math.max(1, r.height) - 0.5) * 14;
    setPar({ x: Math.round(nx * 10) / 10, y: Math.round(ny * 10) / 10 });
  }

  return (
    <div
      className="fsp-stage-card relative overflow-hidden rounded-3xl p-4 sm:p-5"
      onMouseMove={onMove}
      onMouseLeave={() => setPar({ x: 0, y: 0 })}
      data-testid="hero-fsp-showcase"
      aria-label="3D-ядро верификации Федерации спортивного программирования"
    >
      <div className="fsp-hero-visual">
        <div className="fsp-core-glow" aria-hidden="true" />
        <div className="fsp-rings" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </div>
        <span className="fsp-core-shadow" aria-hidden="true" />

        {/* Парящий 3D-медальон грейда в левом верхнем углу сцены */}
        <div
          className="pointer-events-none absolute left-2 top-2 z-20 hidden sm:block"
          style={{
            transform: `translate3d(${-par.x * 0.6}px, ${-par.y * 0.6}px, 0)`,
            transition: "transform 0.45s cubic-bezier(0.16, 1, 0.3, 1)",
          }}
          aria-hidden="true"
        >
          <img
            src={fspMedallion3d}
            width={76}
            height={76}
            alt=""
            className="fsp-float-delayed h-[72px] w-[72px] object-contain drop-shadow-[0_16px_28px_rgba(64,47,255,0.65)]"
            decoding="async"
          />
        </div>

        {/* Центральная левитирующая 3D-скульптура «Ядро Драфта × ФСП» */}
        <div
          className="relative z-10 grid place-items-center"
          style={{
            transform: `translate3d(${par.x}px, ${par.y}px, 0)`,
            transition: "transform 0.45s cubic-bezier(0.16, 1, 0.3, 1)",
          }}
        >
          <span className="fsp-float">
            <img
              src={fspCrystalCore}
              width={260}
              height={260}
              alt="3D-скульптура ядра верификации ИТ-специалистов и достижений ФСП из титана, сапфирового стекла и рубинового ядра"
              className="h-[200px] w-[200px] object-contain sm:h-[235px] sm:w-[235px]"
              fetchPriority="high"
              decoding="async"
            />
          </span>
        </div>

        {/* Три парящие стеклянные орбитальные плашки (Orbit Pills) */}
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
      className="relative flex h-[148px] w-[164px] shrink-0 items-center justify-center select-none sm:h-[164px] sm:w-[184px]"
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
          className="h-[124px] w-[124px] object-contain drop-shadow-[0_24px_36px_rgba(0,0,0,0.75)] sm:h-[142px] sm:w-[142px]"
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
