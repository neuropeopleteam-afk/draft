import { useState } from "react";
import { DemoProfileBadge, DIRECTION_TITLES, GRADE_TITLE_ALL, Toggle } from "../../components/ui";
import { fk } from "../charts";

interface RegionRow {
  title: string;
  confirmed: number | null;
  fsp: number | null;
  real: number | null;
  synthetic: number | null;
  has_synthetic: boolean;
  demand: number;
  gap: number | null;
}

interface DistrictRow {
  id: string;
  short: string;
  title: string;
  center: string;
  confirmed: number | null;
  fsp_confirmed: number | null;
  real_confirmed: number | null;
  synthetic_confirmed: number | null;
  has_synthetic: boolean;
  demand_needs: number;
  demand_invitations: number;
  demand_score: number;
  gap: number | null;
  top_deficit_direction: string;
  top_deficit_direction_title: string;
  competition_hint: string;
  priority: "high" | "medium" | "normal";
  by_direction: Record<string, number | null>;
  by_grade: Record<string, number | null>;
  demand_by_direction: Record<string, number>;
  regions: RegionRow[];
}

interface RegionsMapData {
  k: number;
  total_confirmed: number | null;
  total_real: number | null;
  total_synthetic: number | null;
  has_synthetic: boolean;
  synthetic_note: string;
  districts: DistrictRow[];
  recommendations: {
    district_id: string;
    district_short: string;
    district_title: string;
    direction: string;
    direction_title: string;
    gap: number | null;
    hint: string;
    priority: string;
  }[];
}

// Геометрия федеральных округов России на схематичной SVG-карте (820×340, с запада на восток)
const SVG_POLYGONS: Record<string, { path: string; cx: number; cy: number }> = {
  szfo: {
    path: "M 55,48 L 195,35 L 235,98 L 165,138 L 62,122 Z",
    cx: 145,
    cy: 86,
  },
  cfo: {
    path: "M 50,126 L 165,140 L 185,205 L 85,212 L 45,172 Z",
    cx: 118,
    cy: 175,
  },
  yufo: {
    path: "M 55,216 L 165,208 L 178,266 L 92,275 L 48,248 Z",
    cx: 115,
    cy: 242,
  },
  skfo: {
    path: "M 92,278 L 178,269 L 188,312 L 105,318 Z",
    cx: 140,
    cy: 294,
  },
  pfo: {
    path: "M 188,136 L 285,126 L 298,242 L 182,252 Z",
    cx: 240,
    cy: 190,
  },
  ufo: {
    path: "M 240,56 L 378,52 L 392,235 L 302,240 L 288,124 Z",
    cx: 332,
    cy: 148,
  },
  sfo: {
    path: "M 382,48 L 575,44 L 585,275 L 396,268 Z",
    cx: 484,
    cy: 162,
  },
  dfo: {
    path: "M 579,38 L 788,28 L 798,282 L 589,276 Z",
    cx: 688,
    cy: 156,
  },
};

export function TalentMap({ data }: { data?: RegionsMapData | null }) {
  const [selectedId, setSelectedId] = useState<string>("cfo");
  const [dirFilter, setDirFilter] = useState<string>("all");
  const [gradeFilter, setGradeFilter] = useState<string>("all");
  const [realOnly, setRealOnly] = useState<boolean>(false);

  if (!data?.districts?.length) return null;

  const districts = data.districts;
  const active = districts.find((d) => d.id === selectedId) ?? districts[0];

  const supplyOf = (d: DistrictRow): number | null => {
    if (realOnly) return d.real_confirmed;
    if (dirFilter !== "all") return d.by_direction?.[dirFilter] ?? 0;
    if (gradeFilter !== "all") return d.by_grade?.[gradeFilter] ?? 0;
    return d.confirmed;
  };

  const demandOf = (d: DistrictRow): number => {
    if (dirFilter !== "all") return (d.demand_by_direction?.[dirFilter] ?? 0) + d.demand_needs;
    return d.demand_score;
  };

  const gapOf = (d: DistrictRow): number | null => {
    const sup = supplyOf(d);
    if (sup == null) return null;
    return demandOf(d) - sup;
  };

  return (
    <section className="card space-y-5" data-testid="fsp-talent-map">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand">Региональная аналитика ФСП</p>
          <h2 className="mt-0.5 text-lg font-bold text-brand-night">
            Карта талантов и разрыва «спрос − предложение» по регионам России
          </h2>
          <p className="mt-1 text-sm text-brand-ink/70">
            Подтверждённые кандидаты по федеральным округам и регионам, спрос работодателей и рекомендация, где провести отборочное соревнование ФСП.
          </p>
        </div>
        {data.has_synthetic && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl bg-amber-50/80 px-3 py-2 text-xs text-amber-950 ring-1 ring-amber-300/60">
            <DemoProfileBadge c={{ is_synthetic: true }} />
            <span>
              Реальных: <b>{fk(data.total_real)}</b> · модельных: <b>{fk(data.total_synthetic)}</b>
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[#F7F6FB] p-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs font-semibold text-brand-night">
            Направление:
            <select
              className="input !w-auto !py-1.5 text-xs"
              value={dirFilter}
              onChange={(e) => {
                setDirFilter(e.target.value);
                if (e.target.value !== "all") setGradeFilter("all");
              }}
              aria-label="Фильтр направления на карте"
            >
              <option value="all">Все направления</option>
              {Object.entries(DIRECTION_TITLES).map(([k, t]) => (
                <option key={k} value={k}>{t}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs font-semibold text-brand-night">
            Уровень:
            <select
              className="input !w-auto !py-1.5 text-xs"
              value={gradeFilter}
              onChange={(e) => {
                setGradeFilter(e.target.value);
                if (e.target.value !== "all") setDirFilter("all");
              }}
              aria-label="Фильтр грейда на карте"
            >
              <option value="all">Все грейды</option>
              {Object.entries(GRADE_TITLE_ALL).map(([k, t]) => (
                <option key={k} value={k}>{t}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="min-w-[14rem]">
          <Toggle
            checked={realOnly}
            onChange={setRealOnly}
            label="Только реальные кандидаты (без модельных)"
          />
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBFAFF] p-3">
          <svg
            viewBox="0 0 830 340"
            className="h-auto w-full select-none"
            role="img"
            aria-label="Интерактивная карта федеральных округов России"
          >
            {districts.map((d) => {
              const geo = SVG_POLYGONS[d.id];
              if (!geo) return null;
              const isSel = d.id === active.id;
              const gap = gapOf(d);
              const sup = supplyOf(d);
              const dem = demandOf(d);
              const fill = isSel
                ? "#310F53"
                : gap != null && gap > 0
                  ? "#FCE4EC"
                  : "#ECEAF8";
              const stroke = isSel ? "#E0004C" : gap != null && gap > 0 ? "#E0004C" : "#8A83D1";
              const textFill = isSel ? "#FFFFFF" : "#1D0B30";
              const subFill = isSel ? "#FFD6E4" : "#5B527A";
              return (
                <g
                  key={d.id}
                  className="cursor-pointer transition-opacity hover:opacity-90"
                  onClick={() => setSelectedId(d.id)}
                  role="button"
                  tabIndex={0}
                  aria-label={`${d.title}: кандидатов ${fk(sup)}, спрос ${dem}`}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelectedId(d.id);
                    }
                  }}
                  data-testid={`map-district-${d.id}`}
                >
                  <path
                    d={geo.path}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={isSel ? 3 : 1.5}
                    strokeLinejoin="round"
                  />
                  <text
                    x={geo.cx}
                    y={geo.cy - 10}
                    textAnchor="middle"
                    fontSize="13"
                    fontWeight="800"
                    fill={textFill}
                  >
                    {d.short}
                  </text>
                  <text
                    x={geo.cx}
                    y={geo.cy + 8}
                    textAnchor="middle"
                    fontSize="11"
                    fontWeight="600"
                    fill={subFill}
                  >
                    канд.: {fk(sup)} · спрос: {dem}
                  </text>
                  <text
                    x={geo.cx}
                    y={geo.cy + 24}
                    textAnchor="middle"
                    fontSize="10"
                    fontWeight="700"
                    fill={isSel ? "#FFE082" : gap != null && gap > 0 ? "#B71C1C" : "#2E7D32"}
                  >
                    {gap == null ? "группа < 5" : gap > 0 ? `дефицит +${gap}` : `резерв ${Math.abs(gap)}`}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-brand-ink/65">
            <span className="flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-[#FCE4EC] ring-1 ring-[#E0004C]" /> Дефицит кадров (спрос &gt; предложения)
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-[#ECEAF8] ring-1 ring-[#8A83D1]" /> Достаточный резерв
              </span>
            </span>
            <span>Нажмите на округ для детализации по регионам</span>
          </div>
        </div>

        <div className="flex flex-col justify-between rounded-2xl border border-brand-night/10 bg-white p-4" data-testid="fsp-talent-map-detail">
          <div className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{active.short}</p>
                <h3 className="text-lg font-extrabold text-brand-night">{active.title}</h3>
                <p className="text-xs text-brand-ink/65">Опорные города: {active.center}</p>
              </div>
              {active.has_synthetic && !realOnly && <DemoProfileBadge c={{ is_synthetic: true }} />}
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-[#F7F6FB] p-2.5">
                <p className="text-[11px] text-brand-ink/65">Подтверждено</p>
                <p className="mt-0.5 text-lg font-extrabold text-brand-night">{fk(supplyOf(active))}</p>
                <p className="text-[10px] text-brand-ink/60">с ФСП: {fk(active.fsp_confirmed)}</p>
              </div>
              <div className="rounded-xl bg-[#F7F6FB] p-2.5">
                <p className="text-[11px] text-brand-ink/65">Спрос компаний</p>
                <p className="mt-0.5 text-lg font-extrabold text-brand-night">{demandOf(active)}</p>
                <p className="text-[10px] text-brand-ink/60">потребностей: {active.demand_needs}</p>
              </div>
              <div className="rounded-xl bg-[#F7F6FB] p-2.5">
                <p className="text-[11px] text-brand-ink/65">Разрыв</p>
                <p className={`mt-0.5 text-lg font-extrabold ${(gapOf(active) ?? 0) > 0 ? "text-brand" : "text-emerald-700"}`}>
                  {gapOf(active) == null ? "< 5" : (gapOf(active) ?? 0) > 0 ? `+${gapOf(active)}` : gapOf(active)}
                </p>
                <p className="text-[10px] text-brand-ink/60">спрос − предложение</p>
              </div>
            </div>

            <div className="rounded-xl border border-brand/25 bg-brand-blush/25 p-3 text-xs" data-testid="fsp-competition-hint">
              <p className="font-bold text-brand-night">Где провести соревнование ФСП:</p>
              <p className="mt-1 leading-relaxed text-brand-ink/85">{active.competition_hint}</p>
            </div>

            {active.regions.length > 0 && (
              <div>
                <p className="text-xs font-bold text-brand-night">Субъекты РФ внутри округа</p>
                <ul className="mt-1.5 divide-y divide-brand-night/5 text-xs">
                  {active.regions.slice(0, 5).map((r) => (
                    <li key={r.title} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                      <span className="font-medium text-brand-night">
                        {r.title}{" "}
                        {r.has_synthetic && !realOnly && (
                          <span className="text-[10px] text-amber-800">(вкл. демо-профили)</span>
                        )}
                      </span>
                      <span className="tabular-nums text-brand-ink/75">
                        канд. <b>{fk(realOnly ? r.real : r.confirmed)}</b> · спрос <b>{r.demand}</b>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <p className="mt-3 text-[11px] text-brand-ink/60">{data.synthetic_note}</p>
        </div>
      </div>

      {data.recommendations?.length > 0 && (
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
          <h3 className="text-sm font-bold text-brand-night">
            Приоритетный план региональных соревнований ФСП (по разрыву «спрос − предложение»)
          </h3>
          <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {data.recommendations.slice(0, 3).map((rec) => (
              <button
                key={rec.district_id}
                type="button"
                onClick={() => setSelectedId(rec.district_id)}
                className="rounded-xl border border-brand-night/10 bg-white p-3 text-left text-xs transition hover:border-brand/40"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-brand-night">{rec.district_short} · {rec.direction_title}</span>
                  <span className="rounded-full bg-brand-blush/50 px-2 py-0.5 text-[10px] font-bold text-brand-plum">
                    {rec.gap != null && rec.gap > 0 ? `разрыв +${rec.gap}` : "вовлечение в ФСП"}
                  </span>
                </div>
                <p className="mt-1 text-brand-ink/75">{rec.hint}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
