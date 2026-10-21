import { useState } from "react";
import { DemoProfileBadge, DIRECTION_TITLES, GRADE_TITLE_ALL, Toggle } from "../../components/ui";
import { useDemoUi } from "../../lib/juryMode";
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
  mapped_confirmed?: number | null;
  mapped_real?: number | null;
  has_synthetic: boolean;
  synthetic_note: string;
  unspecified_note?: string;
  city_unspecified?: {
    id: string;
    title: string;
    confirmed: number | null;
    confirmed_raw?: number;
    real_confirmed: number | null;
    real_raw?: number;
    synthetic_confirmed: number | null;
    fsp_confirmed: number | null;
    demand_needs: number;
    demand_invitations: number;
    demand_score: number;
    gap: null;
    note?: string;
  };
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
  real_protocols_vs_hh?: {
    source: string;
    as_of: string;
    k_min: number;
    summary: {
      documents_count: number;
      athlete_results: number;
      unique_athletes: number;
      kms_plus_count: number;
      regions_count: number;
      hh_total_vacancies: number;
      hh_corpus_vacancies: number;
      judges_excluded: boolean;
    };
    by_discipline: {
      discipline: string;
      title: string;
      athletes: number | null;
      results: number | null;
      kms_plus: number | null;
      hh_directions: { id: string; title: string }[];
      hh_vacancies_russia: number;
      hh_vacancies_moscow: number;
      hh_vacancies_spb: number;
      insufficient_data: boolean;
      status_label: string;
    }[];
    by_rank: {
      rank: string;
      results: number | null;
      insufficient_data: boolean;
      status_label: string;
    }[];
    by_region: {
      region: string;
      fo: string;
      fo_title: string;
      fsp_athletes: number | null;
      fsp_results: number | null;
      fsp_kms_plus: number | null;
      top_discipline: string;
      top_discipline_title: string;
      hh_open_vacancies: number | null;
      hh_corpus_vacancies: number | null;
      insufficient_data: boolean;
      status: string;
      status_label: string;
    }[];
  };
}

// Геометрия федеральных округов России на схематичной SVG-карте (с запада на восток, без пустого поля снизу)
const SVG_POLYGONS: Record<string, { path: string; cx: number; cy: number }> = {
  szfo: {
    path: "M 48,36 L 195,28 L 235,96 L 165,134 L 52,118 Z",
    cx: 142,
    cy: 82,
  },
  cfo: {
    path: "M 44,122 L 165,136 L 184,200 L 84,206 L 40,168 Z",
    cx: 116,
    cy: 168,
  },
  yufo: {
    path: "M 50,210 L 165,203 L 178,256 L 88,262 L 44,238 Z",
    cx: 114,
    cy: 233,
  },
  skfo: {
    path: "M 88,265 L 178,259 L 188,308 L 96,312 Z",
    cx: 138,
    cy: 286,
  },
  pfo: {
    path: "M 188,132 L 285,122 L 298,256 L 182,264 Z",
    cx: 240,
    cy: 194,
  },
  ufo: {
    path: "M 240,46 L 378,42 L 392,258 L 302,262 L 288,120 Z",
    cx: 334,
    cy: 152,
  },
  sfo: {
    path: "M 382,38 L 575,34 L 585,292 L 396,284 Z",
    cx: 486,
    cy: 164,
  },
  dfo: {
    path: "M 579,30 L 792,24 L 802,298 L 589,292 Z",
    cx: 690,
    cy: 160,
  },
};

export function TalentMap({ data }: { data?: RegionsMapData | null }) {
  const demoUi = useDemoUi();
  const [selectedId, setSelectedId] = useState<string>("cfo");
  const [dirFilter, setDirFilter] = useState<string>("all");
  const [gradeFilter, setGradeFilter] = useState<string>("all");
  const [realOnly, setRealOnly] = useState<boolean>(!demoUi);

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
    <section className="card min-w-0 overflow-hidden space-y-5" data-testid="fsp-talent-map">
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
        {demoUi && data.has_synthetic && (
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
        {demoUi && (
          <div>
            <Toggle
              checked={realOnly}
              onChange={setRealOnly}
              label="Только реальные кандидаты (без модельных)"
            />
          </div>
        )}
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="min-w-0 self-start rounded-2xl border border-brand-night/10 bg-[#F7F9FF] p-3">
          <svg
            viewBox="32 18 778 302"
            className="block h-auto w-full select-none"
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
              const isDeficit = gap != null && gap > 0;
              const fill = isSel
                ? "#14183B"
                : isDeficit
                  ? "#DCE2FF"
                  : "#D9F5EC";
              const stroke = isSel ? "#402FFF" : isDeficit ? "#402FFF" : "#0D9488";
              const textFill = isSel ? "#FFFFFF" : "#0E1126";
              const subFill = isSel ? "#DCE2FF" : "#28305E";
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
                    strokeWidth={isSel ? 3.5 : 1.8}
                    strokeLinejoin="round"
                  />
                  <text
                    x={geo.cx}
                    y={geo.cy - 8}
                    textAnchor="middle"
                    fontSize={d.id === "skfo" ? "16" : "19"}
                    fontWeight="800"
                    fill={textFill}
                  >
                    {d.short}
                  </text>
                  <text
                    x={geo.cx}
                    y={geo.cy + 8}
                    textAnchor="middle"
                    fontSize={d.id === "skfo" ? "11.5" : "13"}
                    fontWeight="700"
                    fill={subFill}
                  >
                    {fk(sup)} / спрос {dem}
                  </text>
                  {d.id !== "skfo" && (
                    <text
                      x={geo.cx}
                      y={geo.cy + 23}
                      textAnchor="middle"
                      fontSize="12"
                      fontWeight="800"
                      fill={isSel ? "#FFE082" : isDeficit ? "#C61A32" : "#047857"}
                    >
                      {gap == null ? "группа < 5" : gap > 0 ? `дефицит +${gap}` : `резерв ${Math.abs(gap)}`}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {/* Быстрый выбор округа крупными кнопками (особенно удобно на экранах 360 px) */}
          <div className="mt-2.5 flex flex-wrap gap-1.5" aria-label="Быстрый выбор федерального округа">
            {districts.map((d) => {
              const isSel = d.id === active.id;
              const gap = gapOf(d);
              const isDeficit = gap != null && gap > 0;
              return (
                <button
                  key={`pill-${d.id}`}
                  type="button"
                  onClick={() => setSelectedId(d.id)}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-bold transition ${
                    isSel
                      ? "bg-brand-night text-white ring-2 ring-brand"
                      : isDeficit
                        ? "bg-[#DCE2FF]/80 text-brand-night ring-1 ring-brand/40 hover:bg-[#DCE2FF]"
                        : "bg-[#D9F5EC]/80 text-emerald-950 ring-1 ring-teal-600/35 hover:bg-[#D9F5EC]"
                  }`}
                >
                  <span>{d.short}</span>
                  <span className={`font-mono text-[11px] ${isSel ? "text-[#B8B4FF]" : "opacity-75"}`}>{fk(supplyOf(d))}</span>
                </button>
              );
            })}
          </div>
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-brand-night/10 pt-2 px-1 text-xs text-brand-ink/75">
            <span className="flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-1.5 font-medium">
                <span className="h-3 w-3 rounded-sm bg-[#14183B] ring-1 ring-[#402FFF]" /> Выбранный округ
              </span>
              <span className="inline-flex items-center gap-1.5 font-medium">
                <span className="h-3 w-3 rounded-sm bg-[#DCE2FF] ring-1 ring-[#402FFF]" /> Дефицит кадров (спрос &gt; предложения)
              </span>
              <span className="inline-flex items-center gap-1.5 font-medium">
                <span className="h-3 w-3 rounded-sm bg-[#D9F5EC] ring-1 ring-[#0D9488]" /> Достаточный резерв
              </span>
            </span>
            <span className="text-[11px] text-brand-ink/60">Нажмите на округ для детализации</span>
          </div>
        </div>

        <div className="flex min-w-0 flex-col justify-between rounded-2xl border border-brand-night/10 bg-white p-4" data-testid="fsp-talent-map-detail">
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
              <div className="rounded-xl bg-[#EEF1FC] p-2.5">
                <p className="whitespace-nowrap text-[11px] font-medium text-brand-ink/70 [overflow-wrap:normal] [word-break:normal]" title="Подтверждено кандидатов">Подтв.</p>
                <p className="mt-0.5 text-lg font-extrabold text-brand-night">{fk(supplyOf(active))}</p>
                <p className="text-[10px] text-brand-ink/60">с ФСП: {fk(active.fsp_confirmed)}</p>
              </div>
              <div className="rounded-xl bg-[#EEF1FC] p-2.5">
                <p className="text-[11px] font-medium text-brand-ink/70 [overflow-wrap:normal] [word-break:normal]">Спрос компаний</p>
                <p className="mt-0.5 text-lg font-extrabold text-brand-night">{demandOf(active)}</p>
                <p className="text-[10px] text-brand-ink/60">потребностей: {active.demand_needs}</p>
              </div>
              <div className="rounded-xl bg-[#EEF1FC] p-2.5">
                <p className="text-[11px] font-medium text-brand-ink/70 [overflow-wrap:normal] [word-break:normal]">Разрыв</p>
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
                        {demoUi && r.has_synthetic && !realOnly && (
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
          {data.city_unspecified && (
            <div
              className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-brand-night/10 bg-[#F7F6FB] px-3 py-2 text-xs"
              data-testid="fsp-city-unspecified-row"
            >
              <span className="font-semibold text-brand-night">
                {data.city_unspecified.title}{" "}
                <span className="font-normal text-brand-ink/65">(в итогах учтено; на карте и в разрыве округов не учитывается)</span>
              </span>
              <span className="tabular-nums text-brand-ink/80">
                канд. <b>{fk(realOnly ? data.city_unspecified.real_confirmed : data.city_unspecified.confirmed)}</b> · спрос <b>{data.city_unspecified.demand_score}</b>
              </span>
            </div>
          )}
          <p className="mt-2 text-[11px] text-brand-ink/60">
            {demoUi ? data.synthetic_note : (data.unspecified_note ?? "Строка «Город не указан» учитывает профили и потребности без города в общих итогах; на карте и в разрыве округов они не учитываются.")}
          </p>
        </div>
      </div>

      {data.recommendations?.length > 0 && (
        <div className="rounded-2xl border border-brand-night/10 bg-[#F4F6FC] p-4">
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

      {data.real_protocols_vs_hh && (
        <div className="space-y-4 rounded-2xl border border-brand-night/15 bg-white p-4" data-testid="fsp-real-protocols-vs-hh">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-emerald-800">
                Реальные данные без ПДн (152-ФЗ) · Официальные протоколы ФСП × hh.ru
              </p>
              <h3 className="mt-0.5 text-base font-bold text-brand-night">
                Спортсмены из официальных протоколов ФСП (2025–2026) против спроса работодателей hh.ru
              </h3>
              <p className="mt-1 text-xs text-brand-ink/70">
                {data.real_protocols_vs_hh.source}. Записи судейских коллегий (ВК/1К/2К/3К) исключены. Где выборка меньше {data.real_protocols_vs_hh.k_min} — честная отметка «мало данных».
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-lg bg-[#EEF1FC] px-2.5 py-1 font-semibold text-brand-night">
                Протоколов ФСП: {data.real_protocols_vs_hh.summary.documents_count} ({data.real_protocols_vs_hh.summary.athlete_results} результатов)
              </span>
              <span className="rounded-lg bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-900">
                Разрядов КМС / МС: {data.real_protocols_vs_hh.summary.kms_plus_count}
              </span>
              <span className="rounded-lg bg-brand-blush/40 px-2.5 py-1 font-semibold text-brand-plum">
                Вакансий hh.ru: {data.real_protocols_vs_hh.summary.hh_total_vacancies.toLocaleString("ru-RU")}
              </span>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {data.real_protocols_vs_hh.by_rank.map((rk) => (
              <div key={rk.rank} className="rounded-xl border border-brand-night/10 bg-[#F4F6FC] px-3 py-2 text-xs">
                <span className="text-brand-ink/65">ЕВСК {rk.rank}: </span>
                <b className="text-brand-night">
                  {rk.insufficient_data || rk.results == null ? "мало данных" : rk.results.toLocaleString("ru-RU")}
                </b>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs" data-testid="fsp-real-disciplines-table">
              <thead>
                <tr className="border-b border-brand-night/10 text-brand-ink/65">
                  <th className="py-2 pr-3">Дисциплина ФСП (ЕВСК)</th>
                  <th className="py-2 px-2 text-right">Результаты в протоколах</th>
                  <th className="py-2 px-2 text-right">Спортсмены</th>
                  <th className="py-2 px-2 text-right">КМС / МС</th>
                  <th className="py-2 px-3">Профильные ИТ-направления</th>
                  <th className="py-2 pl-2 text-right">Открытых вакансий hh.ru (РФ / Мск / СПб)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-night/5">
                {data.real_protocols_vs_hh.by_discipline.map((d) => (
                  <tr key={d.discipline}>
                    <td className="py-2 pr-3 font-semibold text-brand-night">{d.title}</td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      {d.insufficient_data || d.results == null ? <span className="text-amber-800">мало данных</span> : d.results}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums font-semibold">
                      {d.insufficient_data || d.athletes == null ? <span className="text-amber-800">мало данных</span> : d.athletes}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums text-emerald-800 font-semibold">
                      {d.kms_plus == null ? "мало данных" : d.kms_plus}
                    </td>
                    <td className="py-2 px-3 text-brand-ink/75">
                      {d.hh_directions.map((h) => h.title).join(", ")}
                    </td>
                    <td className="py-2 pl-2 text-right tabular-nums font-semibold text-brand-night">
                      {d.hh_vacancies_russia.toLocaleString("ru-RU")} ({d.hh_vacancies_moscow.toLocaleString("ru-RU")} / {d.hh_vacancies_spb.toLocaleString("ru-RU")})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="overflow-x-auto pt-1">
            <p className="mb-2 text-xs font-bold text-brand-night">
              Субъекты РФ в официальных протоколах ФСП против регионального спроса hh.ru
            </p>
            <table className="w-full text-left text-xs" data-testid="fsp-real-regions-table">
              <thead>
                <tr className="border-b border-brand-night/10 text-brand-ink/65">
                  <th className="py-1.5 pr-3">Субъект РФ</th>
                  <th className="py-1.5 px-2">ФО</th>
                  <th className="py-1.5 px-2 text-right">Спортсмены ФСП</th>
                  <th className="py-1.5 px-2 text-right">КМС / МС</th>
                  <th className="py-1.5 px-2">Ведущая дисциплина</th>
                  <th className="py-1.5 px-2 text-right">Вакансии hh.ru (срез региона)</th>
                  <th className="py-1.5 pl-2">Статус данных</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-night/5">
                {data.real_protocols_vs_hh.by_region.slice(0, 12).map((r) => (
                  <tr key={r.region}>
                    <td className="py-1.5 pr-3 font-medium text-brand-night">{r.region}</td>
                    <td className="py-1.5 px-2 text-brand-ink/70">{r.fo}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums font-semibold">
                      {r.fsp_athletes == null ? "мало данных" : r.fsp_athletes}
                    </td>
                    <td className="py-1.5 px-2 text-right tabular-nums text-emerald-800">
                      {r.fsp_kms_plus == null ? "мало данных" : r.fsp_kms_plus}
                    </td>
                    <td className="py-1.5 px-2 text-brand-ink/75">{r.top_discipline_title}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums">
                      {r.hh_open_vacancies != null
                        ? `${r.hh_open_vacancies.toLocaleString("ru-RU")} откр.`
                        : r.hh_corpus_vacancies != null
                          ? `${r.hh_corpus_vacancies} в корпусе`
                          : <span className="text-amber-800" data-testid="fsp-region-insufficient-data">мало данных</span>}
                    </td>
                    <td className="py-1.5 pl-2">
                      {r.insufficient_data ? (
                        <span className="rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-900" data-testid="fsp-region-insufficient-data">
                          {r.status_label}
                        </span>
                      ) : (
                        <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                          достаточно данных
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
