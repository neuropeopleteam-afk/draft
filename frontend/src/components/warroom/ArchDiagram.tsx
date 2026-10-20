import type { MeasureSpec, NodeId, ScenarioPublic, Tone } from "./types";

export const nf = (v: number, d = 0) =>
  v.toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−");

export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

const NODES: Record<NodeId, { x: number; y: number; w?: number; title: string; sub: string }> = {
  clients: { x: 55, y: 200, w: 92, title: "Клиенты", sub: "веб · мобильные" },
  lb: { x: 178, y: 200, title: "Балансировщик", sub: "входящий трафик" },
  gw: { x: 318, y: 200, title: "API-шлюз", sub: "аутентификация · квоты" },
  core: { x: 470, y: 200, title: "Ядро сервиса", sub: "" },
  pgb: { x: 610, y: 70, title: "Пул транзакций", sub: "мультиплексор БД" },
  pg: { x: 745, y: 70, title: "PostgreSQL", sub: "основной узел" },
  replica: { x: 885, y: 70, title: "PostgreSQL", sub: "реплика чтения" },
  redis: { x: 640, y: 200, title: "Кластер Redis", sub: "кэш · ключи" },
  ext: { x: 885, y: 200, title: "Внешний контур", sub: "" },
  kafka: { x: 745, y: 330, title: "Брокер очередей", sub: "" },
  consumers: { x: 885, y: 330, title: "Обработчики", sub: "" },
};

const NW = 112;
const NH = 54;
const half = (id: NodeId) => (NODES[id].w ?? NW) / 2;

function curve(a: NodeId, b: NodeId) {
  const A = NODES[a];
  const B = NODES[b];
  if (Math.abs(A.x - B.x) < 10) {
    const dir = B.y > A.y ? 1 : -1;
    return `M ${A.x} ${A.y + (dir * NH) / 2} L ${B.x} ${B.y - (dir * NH) / 2}`;
  }
  const x1 = A.x + half(a);
  const x2 = B.x - half(b);
  const dx = (x2 - x1) / 2;
  return `M ${x1} ${A.y} C ${x1 + dx} ${A.y}, ${x2 - dx} ${B.y}, ${x2} ${B.y}`;
}

interface Edge {
  id: string;
  from: NodeId;
  to: NodeId;
  d: string;
  label?: string;
  dashed?: boolean;
  broken?: boolean;
}

function edgesFor(s: ScenarioPublic, activeIds: Set<string>): Edge[] {
  const e: Edge[] = [
    { id: "c-lb", from: "clients", to: "lb", d: curve("clients", "lb") },
    { id: "lb-gw", from: "lb", to: "gw", d: curve("lb", "gw") },
    { id: "gw-core", from: "gw", to: "core", d: curve("gw", "core") },
    { id: "core-redis", from: "core", to: "redis", d: curve("core", "redis") },
    { id: "core-ext", from: "core", to: "ext", d: "M 526 212 C 600 275, 790 275, 829 212" },
    { id: "pg-rep", from: "pg", to: "replica", d: curve("pg", "replica"), dashed: true, label: "репликация" },
    { id: "kafka-cons", from: "kafka", to: "consumers", d: curve("kafka", "consumers") },
  ];
  if (activeIds.has("pgb")) {
    e.push(
      { id: "core-pgb", from: "core", to: "pgb", d: curve("core", "pgb") },
      { id: "pgb-pg", from: "pgb", to: "pg", d: curve("pgb", "pg") }
    );
  } else {
    e.push({ id: "core-pg", from: "core", to: "pg", d: "M 526 188 C 600 188, 640 70, 689 70" });
  }
  if (activeIds.has("outbox")) {
    e.push({ id: "pg-kafka", from: "pg", to: "kafka", d: curve("pg", "kafka"), label: "таблица outbox" });
  } else {
    e.push({
      id: "core-kafka",
      from: "core",
      to: "kafka",
      d: "M 526 214 C 560 330, 640 330, 689 330",
      label: s.id === "kafka" ? "двойная запись ✗" : undefined,
      broken: s.id === "kafka",
    });
  }
  return e;
}

const TONE_COLOR: Record<Tone, { stroke: string; fill: string; packet: string; text: string }> = {
  bad: { stroke: "#ff3b5c", fill: "rgba(255,59,92,0.14)", packet: "#ff3b5c", text: "#ffd0d8" },
  warn: { stroke: "#fbbf24", fill: "rgba(251,191,36,0.12)", packet: "#fbbf24", text: "#fde68a" },
  ok: { stroke: "#34d399", fill: "rgba(52,211,153,0.13)", packet: "#34d399", text: "#bbf7d0" },
  idle: { stroke: "rgba(139,133,255,0.55)", fill: "rgba(99,91,255,0.09)", packet: "#8b85ff", text: "#e0defe" },
};

export function ArchDiagram({
  scenario,
  measuresCatalog,
  stagedIds,
  liveIds,
  nodeTones,
  applied,
  sloMet,
  score,
}: {
  scenario: ScenarioPublic;
  measuresCatalog: MeasureSpec[];
  stagedIds: Set<string>;
  liveIds: Set<string>;
  nodeTones?: Record<NodeId, Tone>;
  applied: boolean;
  sloMet: boolean;
  score: number;
}) {
  const tone = (id: NodeId): Tone => {
    if (nodeTones && nodeTones[id]) return nodeTones[id];
    if (!applied) return scenario.problem.includes(id) ? "bad" : "idle";
    if (sloMet) return "ok";
    return scenario.problem.includes(id) ? (score > 0.6 ? "warn" : "bad") : "idle";
  };

  const activeSet = applied ? liveIds : stagedIds;
  const edges = edgesFor(scenario, activeSet);
  const showPgb = activeSet.has("pgb");
  const visible = (Object.keys(NODES) as NodeId[]).filter((n) => n !== "pgb" || showPgb);

  const badges: Record<string, { label: string; on: boolean; trap: boolean }[]> = {};
  measuresCatalog.forEach((p) => {
    const isLive = applied && liveIds.has(p.id);
    const isStaged = stagedIds.has(p.id);
    if (!isLive && !isStaged) return;
    if (p.id === "pgb" && !showPgb) {
      (badges.pg ??= []).push({ label: p.badge, on: false, trap: false });
      return;
    }
    if (p.id === "pgb") return;
    (badges[p.at] ??= []).push({ label: p.badge, on: isLive, trap: p.trap });
  });

  const fast = applied && sloMet;
  return (
    <svg
      viewBox="0 0 960 400"
      className="h-auto w-full"
      role="img"
      aria-label={`Схема архитектуры: инцидент ${scenario.title}`}
      data-testid="wr-arch-svg"
    >
      <defs>
        <pattern id="wr-grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M 24 0 L 0 0 0 24" fill="none" stroke="rgba(255,255,255,0.04)" />
        </pattern>
        <filter id="wr-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <rect width="960" height="400" fill="url(#wr-grid)" />
      {edges.map((e) => {
        const t: Tone =
          tone(e.from) === "bad" || tone(e.to) === "bad"
            ? "bad"
            : tone(e.from) === "warn" || tone(e.to) === "warn"
              ? "warn"
              : applied && score > 0.65
                ? "ok"
                : "idle";
        const c = TONE_COLOR[t];
        const dur = t === "bad" ? 3.4 : t === "warn" ? 2.2 : fast ? 0.9 : 1.6;
        const n = e.dashed ? 2 : t === "bad" ? 2 : 4;
        return (
          <g key={`${e.id}-${applied}-${t}`}>
            <path
              d={e.d}
              fill="none"
              stroke={c.stroke}
              strokeOpacity={0.45}
              strokeWidth={e.broken && !applied ? 2.5 : 1.8}
              strokeDasharray={e.dashed || (e.broken && !applied) ? "6 6" : undefined}
            />
            {Array.from({ length: n }, (_, i) => (
              <circle key={i} r={t === "bad" ? 4 : 3.2} fill={c.packet} filter="url(#wr-glow)">
                <animateMotion dur={`${dur}s`} repeatCount="indefinite" begin={`${(i * dur) / n}s`} path={e.d} />
              </circle>
            ))}
            {e.label &&
              (() => {
                const m = e.d.match(/(-?\d+(?:\.\d+)?)/g)?.map(Number) ?? [0, 0];
                const lx = (m[0] + m[m.length - 2]) / 2;
                const ly = (m[1] + m[m.length - 1]) / 2;
                return (
                  <text
                    x={lx}
                    y={ly - 6}
                    textAnchor="middle"
                    fontSize="10"
                    fontWeight={700}
                    fill={c.text}
                    style={{ fontFamily: "ui-monospace, monospace" }}
                  >
                    {e.label}
                  </text>
                );
              })()}
          </g>
        );
      })}
      {visible.map((id) => {
        const n = NODES[id];
        const t = tone(id);
        const c = TONE_COLOR[t];
        const w = n.w ?? NW;
        const sub = scenario.labels[id] ?? n.sub;
        const title = id === "ext" && scenario.labels.ext ? scenario.labels.ext : id === "core" ? "Ядро сервиса" : n.title;
        const subline = id === "ext" ? "внешняя система" : id === "core" ? scenario.labels.core ?? "" : sub;
        return (
          <g key={id} data-testid={`wr-node-${id}`} data-tone={t}>
            {t === "bad" && (
              <rect x={n.x - w / 2} y={n.y - NH / 2} width={w} height={NH} rx={12} fill="none" stroke={c.stroke} strokeWidth={2}>
                <animate attributeName="stroke-opacity" values="0.9;0;0.9" dur="1.1s" repeatCount="indefinite" />
                <animate attributeName="stroke-width" values="2;10;2" dur="1.1s" repeatCount="indefinite" />
              </rect>
            )}
            <rect
              x={n.x - w / 2}
              y={n.y - NH / 2}
              width={w}
              height={NH}
              rx={12}
              fill={c.fill}
              stroke={c.stroke}
              strokeWidth={1.6}
              style={{ transition: "all .5s" }}
            />
            <rect x={n.x - w / 2} y={n.y - NH / 2} width={w} height={NH} rx={12} fill="rgba(8,7,20,0.72)" />
            <text x={n.x} y={n.y - 4} textAnchor="middle" fontSize="11.5" fontWeight={800} fill="#fff">
              {title.slice(0, 18)}
            </text>
            <text
              x={n.x}
              y={n.y + 12}
              textAnchor="middle"
              fontSize="9.5"
              fill={c.text}
              style={{ fontFamily: "ui-monospace, monospace" }}
            >
              {subline.slice(0, 22)}
            </text>
            <circle cx={n.x + w / 2 - 9} cy={n.y - NH / 2 + 9} r={3.5} fill={c.stroke} />
            {(badges[id] ?? []).map((b, i) => {
              const by = n.y + NH / 2 + 6 + i * 17;
              const bw = Math.max(58, b.label.length * 6.4 + 14);
              const col = b.trap ? "#fbbf24" : b.on ? "#34d399" : "rgba(255,255,255,0.65)";
              return (
                <g key={b.label}>
                  <rect
                    x={n.x - bw / 2}
                    y={by}
                    width={bw}
                    height={14}
                    rx={7}
                    fill={b.on ? (b.trap ? "rgba(251,191,36,0.18)" : "rgba(52,211,153,0.18)") : "rgba(255,255,255,0.05)"}
                    stroke={col}
                    strokeDasharray={b.on ? undefined : "3 3"}
                  />
                  <text
                    x={n.x}
                    y={by + 10}
                    textAnchor="middle"
                    fontSize="9"
                    fontWeight={700}
                    fill={col}
                    style={{ fontFamily: "ui-monospace, monospace" }}
                  >
                    {b.on ? "✓ " : "◌ "}
                    {b.label}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

export function MetricTile({
  label,
  value,
  unit,
  tone,
  hint,
}: {
  label: string;
  value: string;
  unit?: string;
  tone: Tone;
  hint?: string;
}) {
  const ring =
    tone === "bad"
      ? "border-rose-500/60 shadow-[0_0_24px_-6px_rgba(244,63,94,0.65)]"
      : tone === "warn"
        ? "border-amber-400/60"
        : tone === "ok"
          ? "border-emerald-400/60 shadow-[0_0_24px_-8px_rgba(52,211,153,0.65)]"
          : "border-white/10";
  const col =
    tone === "bad" ? "text-rose-300" : tone === "warn" ? "text-amber-200" : tone === "ok" ? "text-emerald-300" : "text-white";
  return (
    <div className={`rounded-xl border bg-white/[0.03] px-3 py-2.5 transition-all duration-300 ${ring}`}>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-white/55">{label}</p>
      <p className={`mt-0.5 font-mono text-lg font-extrabold tabular-nums md:text-xl ${col}`}>
        {value}
        {unit && <span className="ml-1 text-xs font-semibold text-white/50">{unit}</span>}
      </p>
      {hint && <p className="mt-0.5 text-[10px] text-white/45">{hint}</p>}
    </div>
  );
}

const LEVELS: { key: string; name: string; from: number }[] = [
  { key: "junior", name: "Junior", from: 0.0 },
  { key: "middle", name: "Middle", from: 0.35 },
  { key: "senior", name: "Senior", from: 0.62 },
  { key: "lead", name: "Lead", from: 0.78 },
  { key: "principal", name: "Principal", from: 0.9 },
];

export function EngineeringLevelMeter({
  score,
  confirmedGrade,
  targetGrade,
  pending,
}: {
  score: number;
  confirmedGrade: string;
  targetGrade: string;
  pending: boolean;
}) {
  const pct = clamp(Math.round(score * 100), 0, 100);
  const currentTitle = LEVELS.find((l) => l.key === confirmedGrade.toLowerCase())?.name ?? "Middle";
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4" data-testid="wr-theta">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
          Оценка боевого этапа · цель {targetGrade.toUpperCase()}
        </p>
        <p className="font-mono text-base font-extrabold text-white">
          <span className={pct >= 82 ? "text-emerald-300" : pct >= 65 ? "text-indigo-300" : "text-amber-200"}>
            {pct} %
          </span>{" "}
          <span className="text-xs text-white/60">· уровень {currentTitle}</span>
        </p>
      </div>
      <div className="relative mt-3 h-7">
        <div className="absolute inset-x-0 top-2.5 h-2.5 rounded-full bg-gradient-to-r from-rose-500/50 via-indigo-500/60 to-emerald-400/70" />
        <div
          className="absolute top-0 -ml-2 h-7 w-4 transition-all duration-500 ease-out"
          style={{ left: `${clamp(pct, 2, 98)}%` }}
        >
          <div
            className={`mx-auto h-7 w-1.5 rounded-full ${
              pending ? "animate-pulse bg-white/70" : "bg-white shadow-[0_0_12px_rgba(255,255,255,0.9)]"
            }`}
          />
        </div>
      </div>
      <div className="mt-2 grid grid-cols-5 gap-1 text-center text-[10px] font-semibold text-white/45">
        {LEVELS.map((l) => (
          <span
            key={l.key}
            className={`rounded-md px-0.5 py-1 leading-tight ${
              currentTitle === l.name ? "bg-white/15 text-white" : ""
            }`}
          >
            {l.name}
          </span>
        ))}
      </div>
      <details className="mt-2 text-[11px] text-white/50">
        <summary className="cursor-pointer font-semibold text-indigo-300/80 hover:text-indigo-200">
          Как считается вклад боевого этапа в грейд
        </summary>
        <p className="mt-1 leading-relaxed text-white/60">
          Итоговый балл складывается из объективного выполнения показателей надёжности (SLO) в рамках бюджета (45 %),
          корректности патча кода (25 %) и проверки письменного обоснования по рубрике с дословными цитатами (30 %).
          Результат учитывается как задание высокой информативности без угадывания для подтверждения уровней Senior, Lead и Principal.
        </p>
      </details>
    </div>
  );
}
