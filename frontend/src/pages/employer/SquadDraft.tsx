// Командный Драфт ФСП (/employer/squad): сборка сыгранного звена из 4 человек под проект, калькулятор экономики найма
// для HRD и «рентген» кода кандидата. Три вкладки, подробности — по клику (details / модалка), без перегруза экрана.
// Профили обезличены (C-…), как в подборке до принятия приглашения; расчёт идёт на клиенте за миллисекунды.
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Modal, NB, Seg, Toggle, fmtHours, rub } from "../../components/ui";

type Tab = "squad" | "roi" | "dna";
const TABS: { id: Tab; title: string }[] = [
  { id: "squad", title: "Командный Драфт" },
  { id: "roi", title: "Экономика найма" },
  { id: "dna", title: "Рентген кода" },
];

const mln = (v: number) => `${(v / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}${NB}млн${NB}₽`;
const n0 = (v: number) => Math.round(v).toLocaleString("ru-RU");
const th = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function SquadDraft() {
  const [sp, setSp] = useSearchParams();
  const tab = (TABS.some((t) => t.id === sp.get("tab")) ? sp.get("tab") : "squad") as Tab;
  const setTab = (t: Tab) => setSp(t === "squad" ? {} : { tab: t }, { replace: true });
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Командный Драфт ФСП"
        subtitle="Выберите тип проекта и смоделируйте звено из 2–10 специалистов под месячный бюджет ФОТ. Рядом — калькулятор экономики найма и статический рентген кода (пример расчёта)." />
      <Alert kind="info">
        <b>Интерактивный пример расчёта.</b> Профили в таблице звена — модельные образцы для планирования бюджета и ролей проекта. Для отправки реальных приглашений живым кандидатам используйте раздел <Link to="/employer/needs" className="font-semibold text-brand hover:underline">«Потребности и вакансии»</Link> или <Link to="/employer/candidates" className="font-semibold text-brand hover:underline">«Поиск по базе»</Link>.
      </Alert>
      <Seg label="Раздел Командного Драфта" value={tab} onChange={setTab} options={TABS} />
      {tab === "squad" && <SquadBuilder />}
      {tab === "roi" && <HireRoi />}
      {tab === "dna" && <CodeDna />}
    </div>
  );
}

function Range({ id, label, value, min, max, step, onChange, fmt, hint }: {
  id: string; label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt: (v: number) => string; hint?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-semibold text-brand-night">{label}</label>
        <span className="text-sm font-bold tabular-nums text-brand-night" aria-live="polite">{fmt(value)}</span>
      </div>
      <input id={id} type="range" className="mt-2 w-full accent-[#402FFF]" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} aria-valuetext={fmt(value)} />
      <div className="flex justify-between text-[11px] text-brand-ink/55"><span>{fmt(min)}</span>{hint && <span>{hint}</span>}<span>{fmt(max)}</span></div>
    </div>
  );
}

function Kpi({ label, value, hint, tone = "night" }: { label: string; value: string; hint?: string; tone?: "night" | "ok" | "warn" }) {
  const c = tone === "ok" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : "text-brand-night";
  return (
    <div className="rounded-2xl border border-brand-night/10 bg-[#F4F6FC] p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand-lavender">{label}</p>
      <p className={`mt-1.5 text-2xl font-extrabold tabular-nums ${c}`}>{value}</p>
      {hint && <p className="mt-1 text-xs leading-relaxed text-brand-ink/65">{hint}</p>}
    </div>
  );
}

// ================================================================== 1. Командный Драфт (Squad Builder)

interface Pick {
  code: string; grade: string; theta: number; salary: number; fsp: string | null; key: string; skills: string[];
}
interface Role { title: string; options: [Pick, Pick] }
interface Project { id: string; title: string; short: string; graph: string[]; roles: Role[] }

const P = (code: string, grade: string, theta: number, salary: number, fsp: string | null, key: string, skills: string[]): Pick =>
  ({ code, grade, theta, salary, fsp, key, skills });

// Первый вариант в роли — разрядник ФСП (T2), второй — сильный кандидат без истории ФСП или дешевле с белым пятном.
const PROJECTS: Project[] = [
  {
    id: "fintech", title: "Запуск высоконагруженного финтех/платёжного ядра", short: "Платёжное ядро",
    graph: ["Go / Java", "PostgreSQL", "Kafka", "Идемпотентность платежей", "ClickHouse", "Airflow", "Kubernetes", "SLO и наблюдаемость", "PCI DSS", "Нагрузочные тесты"],
    roles: [
      { title: "Backend Lead", options: [
        P("C-7KQ2ZD", "Lead", 2.14, 360_000, "Призёр Кубка России по продуктовому программированию", "3f9a…b71c", ["Go / Java", "PostgreSQL", "Kafka", "Идемпотентность платежей"]),
        P("C-4RM8TA", "Lead", 1.88, 325_000, null, "a1d4…09fe", ["Go / Java", "PostgreSQL", "Идемпотентность платежей"]),
      ] },
      { title: "Data Engineer Middle", options: [
        P("C-9VHX3L", "Middle", 0.92, 200_000, "КМС · спортивное программирование", "77c2…e5a0", ["ClickHouse", "Airflow", "Kafka"]),
        P("C-2NB6QW", "Middle", 1.01, 215_000, null, "c90b…4d17", ["ClickHouse", "Airflow", "Kafka"]),
      ] },
      { title: "DevOps / SRE Senior", options: [
        P("C-5TJ1PK", "Senior", 1.63, 270_000, "1 спортивный разряд", "e4f8…2a6b", ["Kubernetes", "SLO и наблюдаемость", "Нагрузочные тесты"]),
        P("C-8LW4FD", "Senior", 1.41, 240_000, null, "0b3e…77d1", ["Kubernetes", "SLO и наблюдаемость"]),
      ] },
      { title: "Security / QA Middle", options: [
        P("C-3YC7MN", "Middle", 0.84, 170_000, "2 спортивный разряд", "9d51…c3f2", ["PCI DSS", "Нагрузочные тесты"]),
        P("C-6GZ9RB", "Middle", 0.71, 150_000, null, "5a7c…18e9", ["PCI DSS"]),
      ] },
    ],
  },
  {
    id: "ai", title: "Разработка продуктового ИИ-сервиса с нуля", short: "ИИ-сервис",
    graph: ["PyTorch", "RAG и векторный поиск", "MLOps", "Python / FastAPI", "PostgreSQL", "React / TypeScript", "Дизайн-система", "Требования и BPMN", "Метрики качества модели"],
    roles: [
      { title: "Data / ML Senior", options: [
        P("C-1QF5XE", "Senior", 1.97, 340_000, "Призёр Чемпионата России · ИИ-трек", "6c0e…a94d", ["PyTorch", "RAG и векторный поиск", "MLOps", "Метрики качества модели"]),
        P("C-7DK3UV", "Senior", 1.72, 300_000, null, "b2f1…5e08", ["PyTorch", "RAG и векторный поиск", "Метрики качества модели"]),
      ] },
      { title: "Backend Middle", options: [
        P("C-4HS8ZJ", "Middle", 0.95, 210_000, "1 спортивный разряд", "d83a…71bc", ["Python / FastAPI", "PostgreSQL"]),
        P("C-9PW2CT", "Middle", 1.04, 225_000, null, "17e6…c0a2", ["Python / FastAPI", "PostgreSQL"]),
      ] },
      { title: "Frontend Middle", options: [
        P("C-2MX6LR", "Middle", 0.88, 195_000, "КМС · продуктовое программирование", "f05d…3b9e", ["React / TypeScript", "Дизайн-система"]),
        P("C-5BN1YG", "Middle", 0.74, 170_000, null, "8a2c…d6f4", ["React / TypeScript"]),
      ] },
      { title: "System Analyst Middle", options: [
        P("C-8TV4QH", "Middle", 0.79, 180_000, "2 спортивный разряд", "3e7b…92a1", ["Требования и BPMN", "Метрики качества модели"]),
        P("C-3RJ7KW", "Middle", 0.66, 160_000, null, "c1a9…4f60", ["Требования и BPMN"]),
      ] },
    ],
  },
  {
    id: "mobile", title: "Масштабирование мобильного супераппа", short: "Мобильный суперапп",
    graph: ["Kotlin / Swift", "Модульная архитектура", "Go / Java", "gRPC", "Redis", "Appium / Kaspresso", "CI/CD", "Kubernetes", "Feature flags"],
    roles: [
      { title: "Mobile Senior", options: [
        P("C-6WE3NA", "Senior", 1.81, 310_000, "Призёр Кубка России · мобильный трек", "4b8f…e21d", ["Kotlin / Swift", "Модульная архитектура", "Feature flags"]),
        P("C-1ZL9PX", "Senior", 1.59, 280_000, null, "e6d0…7ac3", ["Kotlin / Swift", "Модульная архитектура"]),
      ] },
      { title: "Backend Senior", options: [
        P("C-4KC2VM", "Senior", 1.74, 300_000, "1 спортивный разряд", "92f5…0b6e", ["Go / Java", "gRPC", "Redis"]),
        P("C-7SY8DQ", "Senior", 1.83, 315_000, null, "0d4a…c8f7", ["Go / Java", "gRPC", "Redis"]),
      ] },
      { title: "QA Automation Middle", options: [
        P("C-9AR5TF", "Middle", 0.86, 180_000, "КМС · спортивное программирование", "a7c3…5d92", ["Appium / Kaspresso", "CI/CD"]),
        P("C-2EH1WB", "Middle", 0.72, 160_000, null, "5f1e…b40a", ["Appium / Kaspresso"]),
      ] },
      { title: "DevOps Middle", options: [
        P("C-5UJ6GL", "Middle", 0.91, 190_000, "2 спортивный разряд", "c4e7…13d8", ["Kubernetes", "CI/CD"]),
        P("C-8NP3ZK", "Middle", 0.83, 175_000, null, "7b90…e6c1", ["Kubernetes", "CI/CD"]),
      ] },
    ],
  },
  {
    id: "critical", title: "Импортозамещение и защита критической инфраструктуры", short: "Критическая инфраструктура",
    graph: ["187-ФЗ и ФСТЭК", "SOC и SIEM", "Astra Linux / РЕД ОС", "Kubernetes", "Ansible", "Go / Java", "PostgreSQL / Postgres Pro", "Пентест", "Регресс и приёмка"],
    roles: [
      { title: "Security Lead", options: [
        P("C-3MQ8XC", "Lead", 2.06, 370_000, "Призёр Чемпионата России · ИБ-трек", "e2b6…9f4a", ["187-ФЗ и ФСТЭК", "SOC и SIEM", "Пентест"]),
        P("C-6VT1HN", "Lead", 1.79, 330_000, null, "18c4…d7e3", ["187-ФЗ и ФСТЭК", "SOC и SIEM"]),
      ] },
      { title: "DevOps Senior", options: [
        P("C-1JD4RS", "Senior", 1.69, 280_000, "1 спортивный разряд", "b5a0…62fc", ["Astra Linux / РЕД ОС", "Kubernetes", "Ansible"]),
        P("C-9FX7ME", "Senior", 1.52, 255_000, null, "f3d8…a10b", ["Kubernetes", "Ansible"]),
      ] },
      { title: "Backend Senior", options: [
        P("C-4ZW2BY", "Senior", 1.71, 290_000, "КМС · продуктовое программирование", "0c9e…4b75", ["Go / Java", "PostgreSQL / Postgres Pro"]),
        P("C-7GL5QT", "Senior", 1.78, 300_000, null, "6e2f…c3a8", ["Go / Java", "PostgreSQL / Postgres Pro"]),
      ] },
      { title: "QA Senior", options: [
        P("C-2CK9VD", "Senior", 1.48, 230_000, "2 спортивный разряд", "a4d1…87e2", ["Регресс и приёмка", "Пентест"]),
        P("C-5HB3NF", "Senior", 1.30, 205_000, null, "93b7…1f0d", ["Регресс и приёмка"]),
      ] },
    ],
  },
];

const EXTRA_ROLES: Role[] = [
  { title: "Frontend Senior", options: [
    P("C-5RT2LP", "Senior", 1.68, 280_000, "1 спортивный разряд", "4c9a…11e2", ["React / TypeScript", "Дизайн-система"]),
    P("C-8MN4VX", "Senior", 1.54, 255_000, null, "7d2b…83f0", ["React / TypeScript"]),
  ] },
  { title: "System Analyst Senior", options: [
    P("C-6KP9WA", "Senior", 1.58, 265_000, "КМС · продуктовое программирование", "2e8f…90c4", ["Требования и BPMN", "SLO и наблюдаемость"]),
    P("C-3JH7QD", "Senior", 1.42, 240_000, null, "9a1c…44b8", ["Требования и BPMN"]),
  ] },
  { title: "Backend Middle+", options: [
    P("C-2DF8SN", "Middle", 1.18, 230_000, "1 спортивный разряд", "8b3e…52a9", ["Go / Java", "PostgreSQL", "Python / FastAPI"]),
    P("C-9WL3KC", "Middle", 1.05, 210_000, null, "1f4d…67e1", ["Go / Java", "PostgreSQL"]),
  ] },
  { title: "QA Automation Senior", options: [
    P("C-7BV4ZM", "Senior", 1.51, 245_000, "2 спортивный разряд", "5c6a…39d7", ["Нагрузочные тесты", "CI/CD", "Регресс и приёмка"]),
    P("C-1XY6TR", "Senior", 1.36, 220_000, null, "3d8b…72c5", ["Нагрузочные тесты", "CI/CD"]),
  ] },
  { title: "Data / ML Middle", options: [
    P("C-4QN8HJ", "Middle", 1.12, 235_000, "КМС · спортивное программирование", "6a2f…18b3", ["PyTorch", "ClickHouse", "Метрики качества модели"]),
    P("C-8PC2VE", "Middle", 0.98, 210_000, null, "0e7c…95a4", ["PyTorch", "ClickHouse"]),
  ] },
  { title: "DevSecOps Middle", options: [
    P("C-3LS9GW", "Middle", 1.08, 225_000, "2 спортивный разряд", "7f1b…46d9", ["Kubernetes", "PCI DSS", "SOC и SIEM"]),
    P("C-6ZR5KT", "Middle", 0.94, 200_000, null, "2b9d…81e6", ["Kubernetes", "PCI DSS"]),
  ] },
];

const BUDGET_MIN = 450_000, BUDGET_MAX = 3_200_000;
const AGENCY_FEE = 0.2;  // комиссия агентства: 20 % годового дохода специалиста
const FSP_BONUS = 0.3;   // при приоритете ФСП разряд T2 весит как +0,3 θ

/** Лучший по баллу кандидат в каждой роли; при нехватке бюджета — замена с наименьшей потерей балла на рубль. */
function assembleRoles(roles: Role[], budget: number, fspFirst: boolean): number[] {
  const score = (x: Pick) => x.theta + (fspFirst && x.fsp ? FSP_BONUS : 0) + x.skills.length * 0.05;
  const pick: number[] = roles.map((r) => (score(r.options[0]) >= score(r.options[1]) ? 0 : 1));
  const sum = () => pick.reduce((s, o, i) => s + roles[i].options[o].salary, 0);
  while (sum() > budget) {
    let best = -1, bestCost = Infinity;
    roles.forEach((r, i) => {
      const cur = r.options[pick[i]], alt = r.options[1 - pick[i]];
      const saved = cur.salary - alt.salary;
      if (saved <= 0) return;
      const cost = (score(cur) - score(alt)) / saved;
      if (cost < bestCost) { bestCost = cost; best = i; }
    });
    if (best < 0) break;
    pick[best] = 1 - pick[best];
  }
  return pick;
}

function nextSlots(n: number): string[] {
  const out: string[] = [];
  const d = new Date();
  const hours = ["11:00", "14:30", "16:00", "12:00"];
  while (out.length < n) {
    d.setDate(d.getDate() + 1);
    if (d.getDay() === 0 || d.getDay() === 6) continue;
    out.push(`${d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" })}, ${hours[out.length % hours.length]}`);
  }
  return out;
}

function SquadBuilder() {
  const navigate = useNavigate();
  const [pid, setPid] = useState(PROJECTS[0].id);
  const [teamSize, setTeamSize] = useState<number>(4);
  const [budget, setBudget] = useState(1_200_000);
  const [fspFirst, setFspFirst] = useState(true);
  const [manual, setManual] = useState<Record<string, number[]>>({});  // ручные замены: ключ — проект, размер, бюджет и фильтр
  const [sent, setSent] = useState(false);
  const p = PROJECTS.find((x) => x.id === pid)!;
  const activeRoles = useMemo(() => [...p.roles, ...EXTRA_ROLES].slice(0, teamSize), [p, teamSize]);
  const mkey = `${pid}|${teamSize}|${budget}|${fspFirst}`;
  const auto = useMemo(() => assembleRoles(activeRoles, budget, fspFirst), [activeRoles, budget, fspFirst]);
  const pick = manual[mkey] ?? auto;
  const team = activeRoles.map((r, i) => ({ role: r.title, x: r.options[pick[i] ?? 0], alt: r.options[1 - (pick[i] ?? 0)], i }));
  const total = team.reduce((s, t) => s + t.x.salary, 0);
  const covered = new Set(team.flatMap((t) => t.x.skills));
  const gaps = p.graph.filter((s) => !covered.has(s));
  const coverage = teamSize >= 4 ? Math.round(((p.graph.length - gaps.length) / p.graph.length) * 100) : Math.min(100, Math.round((covered.size / Math.max(1, Math.ceil(p.graph.length * 0.6))) * 100));
  const fspCount = team.filter((t) => t.x.fsp).length;
  const synergy = Math.max(60, Math.min(98, 80 + Math.round((16 * fspCount) / Math.max(1, teamSize)) - 3 * (teamSize >= 4 ? gaps.length : 0)));
  const savings = total * 12 * AGENCY_FEE;
  const over = total - budget;
  const slots = useMemo(() => nextSlots(10), []);
  const swap = (i: number) => { const next = [...pick]; next[i] = 1 - next[i]; setManual({ ...manual, [mkey]: next }); };
  const handleSizeChange = (sz: number) => {
    setTeamSize(sz);
    setBudget(sz * 300_000);
  };

  return (
    <div className="space-y-5">
      <section className="card space-y-5" aria-label="Параметры звена">
        <div>
          <h2 className="text-lg font-bold text-brand-night">1. Проект компании</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Типовой ИТ-проект">
            {PROJECTS.map((x) => (
              <button key={x.id} type="button" role="radio" aria-checked={x.id === pid} onClick={() => setPid(x.id)}
                className={`rounded-xl border p-3 text-left text-sm transition-colors ${x.id === pid ? "border-brand-strong bg-brand-blush/40" : "border-brand-night/10 hover:bg-brand-blush/20"}`}>
                <span className="block font-bold text-brand-night">{x.title}</span>
                <span className="mt-0.5 block text-xs text-brand-ink/65">{x.roles.map((r) => r.title).join(" · ")}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-brand-night/10 pt-4">
          <div>
            <p className="text-sm font-semibold text-brand-night">2. Размер команды (от мини-звена до полного ИТ-отдела)</p>
            <p className="text-xs text-brand-ink/65">Выберите от 2 до 10 специалистов — состав и бюджет масштабируются автоматически</p>
          </div>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Размер команды">
            {[2, 3, 4, 5, 6, 7, 8, 9, 10].map((sz) => (
              <button key={sz} type="button" role="radio" aria-checked={teamSize === sz} onClick={() => handleSizeChange(sz)}
                className={`rounded-xl px-3.5 py-2 text-xs font-bold transition ${teamSize === sz ? "bg-brand text-white shadow-sm" : "bg-[#EEF1FC] text-brand-night hover:bg-brand-blush/60"}`}>
                {sz} чел.
              </button>
            ))}
          </div>
        </div>
        <div className="grid items-end gap-5 md:grid-cols-[1fr_auto]">
          <Range id="squad-budget" label="3. Месячный бюджет ФОТ команды" value={budget} min={BUDGET_MIN} max={BUDGET_MAX} step={50_000}
            onChange={setBudget} fmt={(v) => rub(v)} />
          <div className="md:w-72">
            <Toggle checked={fspFirst} onChange={setFspFirst} label="Приоритет призёрам и разрядникам ФСП"
              hint="Разряд подтверждён федерацией — даёт приоритет при равном уровне" />
          </div>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi label="Покрытие графа технологий" value={`${coverage}${NB}%`} tone={coverage < 100 ? "warn" : "ok"}
          hint={coverage < 100 && gaps.length ? `Белые пятна: ${gaps.join(", ")}` : "Без белых пятен: каждый навык проекта закрыт"} />
        <Kpi label="Индекс синергии (оценка по формуле)" value={`${synergy}${NB}%`} tone={synergy >= 90 ? "ok" : "night"}
          hint={`Оценка по формуле (80 + доля призёров ФСП − пробелы графа) · ${fspCount} из ${teamSize} с опытом турниров ФСП`} />
        <Kpi label="Экономия против агентства" value={mln(savings)} hint={`Комиссия 20${NB}% годового дохода команды не нужна`} />
      </div>

      <section className="card space-y-4" aria-label="Собранное звено">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-bold text-brand-night">Команда «{p.short}» · {teamSize} чел.</h2>
          <p className={`text-sm font-semibold tabular-nums ${over > 0 ? "text-amber-700" : "text-brand-ink/70"}`}>
            ФОТ {rub(total)} из {rub(budget)}
          </p>
        </div>
        {over > 0 && <Alert kind="info">Бюджета не хватает на {rub(over)} в месяц даже после замен — увеличьте ФОТ или замените роль вручную.</Alert>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-brand-night/10 text-left text-[11px] uppercase tracking-[0.08em] text-brand-lavender">
                <th className="py-2 pr-3 font-semibold">Роль · профиль</th>
                <th className="py-2 pr-3 font-semibold">Грейд</th>
                <th className="py-2 pr-3 font-semibold" title="Оценка по адаптивной шкале теста">Уровень по тесту</th>
                <th className="py-2 pr-3 font-semibold">Паспорт</th>
                <th className="py-2 pr-3 font-semibold">ФСП</th>
                <th className="py-2 pr-3 text-right font-semibold">Ожидания</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {team.map((t) => (
                <tr key={t.role} className="border-b border-brand-night/5 align-top last:border-0">
                  <td className="py-3 pr-3">
                    <p className="font-bold text-brand-night">{t.role}</p>
                    <p className="font-mono text-xs text-brand-ink/65">{t.x.code}</p>
                  </td>
                  <td className="py-3 pr-3"><span className="font-semibold">{t.x.grade}</span><span className="block text-xs text-emerald-700">✓ подтверждён тестом</span></td>
                  <td className="py-3 pr-3">
                    <span className="font-semibold tabular-nums">{th(t.x.theta)}</span>
                    <span className="mt-1 block h-1.5 w-24 rounded-full bg-brand-night/10" aria-hidden="true">
                      <span className="block h-1.5 rounded-full bg-brand-strong" style={{ width: `${Math.round(((t.x.theta + 3) / 6) * 100)}%` }} />
                    </span>
                  </td>
                  <td className="py-3 pr-3"><span className="font-mono text-xs" title="Как устроено: асимметричная цифровая подпись Ed25519">Ключ {t.x.key}</span><span className="block text-xs text-emerald-700">✓ подпись верна</span></td>
                  <td className="py-3 pr-3 text-xs">{t.x.fsp ? <><span className="chip !px-2 !py-0.5">реестр ФСП</span> <span className="mt-1 block max-w-[13rem] leading-snug">{t.x.fsp}</span></> : <span className="text-brand-ink/55">нет истории — нейтрально</span>}</td>
                  <td className="py-3 pr-3 text-right font-semibold tabular-nums">{rub(t.x.salary)}</td>
                  <td className="py-3 text-right">
                    <button type="button" className="text-xs font-semibold text-brand hover:underline" onClick={() => swap(t.i)}
                      title={`${t.alt.code}: индекс ${th(t.alt.theta)}, ${rub(t.alt.salary)}`}>Заменить</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-brand-night/10 pt-4">
          <p className="text-xs text-brand-ink/65">Модельный расчёт звена ({teamSize} ролей). Реальные приглашения отправляются из подборки по потребности.</p>
          <button type="button" className="btn-primary" onClick={() => setSent(true)} data-testid="squad-batch-offer">
            Предпросмотр пакетного оффера ({teamSize} ролей, пример)
          </button>
        </div>
      </section>

      <Modal open={sent} onClose={() => setSent(false)} title={`Пример пакетного оффера · ${teamSize} ролей`}>
        <div className="space-y-4">
          <Alert kind="info">Это демонстрационный пример расчёта звена «{p.short}» — реальные приглашения кандидатам отсюда не отправляются. Чтобы пригласить реальных кандидатов с зарплатной вилкой и слотами интервью, создайте подборку в разделе «Потребности и вакансии».</Alert>
          <ul className="divide-y divide-brand-night/10 text-sm">
            {team.map((t, i) => (
              <li key={t.x.code} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                <span><b className="text-brand-night">{t.role}</b> <span className="font-mono text-xs text-brand-ink/65">{t.x.code} (модельный профиль)</span></span>
                <span className="text-xs text-brand-ink/75">{rub(Math.round(t.x.salary * 0.95 / 5000) * 5000)} – {rub(Math.round(t.x.salary * 1.1 / 5000) * 5000)} · пример слота: {slots[i]}</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setSent(false)}>Закрыть пример</button>
            <button type="button" className="btn-primary" onClick={() => navigate("/employer/needs")}>Перейти к потребностям и подборкам</button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ================================================================== 2. Экономика найма (Bad-Hire Shield & ROI)

// Метрики «Драфта» и допущения модели — показываются в «Как считаем».
const M = {
  interviewsPerHire: 8, seniorsPerInterview: 2, hoursPerInterview: 1.5,  // классика: 8 техсобеседований × 2 Senior × 1,5 ч
  draftFinalists: 2, draftHours: 1,                                       // «Драфт»: 2 финалиста × 1 Senior × 1 ч
  seniorHourRate: 2_400,                                                  // ₽/ч Senior с налогами
  inflatedBefore: 0.58, inflatedAfter: 0.069,                             // «раздутые» резюме в топ-10
  slipToOffer: 0.25,                                                      // каждое 4-е раздутое резюме из топ-10 доходит до оффера
  badHireMonths: 6, payroll: 1.3,                                         // цена ошибки: 6 месяцев ФОТ с налогами
  tthBefore: 42, tthAfter: 3,                                             // Time-to-Hire, дни
  agencyFee: 0.2,                                                         // комиссия агентства, доля годового дохода
};

export function HireRoi() {
  const [hires, setHires] = useState(40);
  const [salary, setSalary] = useState(250_000);
  const r = useMemo(() => {
    const hoursClassic = M.interviewsPerHire * M.seniorsPerInterview * M.hoursPerInterview;
    const hoursDraft = M.draftFinalists * M.draftHours;
    const hoursSaved = hires * (hoursClassic - hoursDraft);
    const badBefore = hires * M.inflatedBefore * M.slipToOffer, badAfter = hires * M.inflatedAfter * M.slipToOffer;
    const badCost = M.badHireMonths * salary * M.payroll;
    const daysSaved = M.tthBefore - M.tthAfter;
    const seatDay = (salary * M.payroll) / 30;
    const agency = hires * salary * 12 * M.agencyFee;
    const res = {
      hoursSaved, hoursRub: hoursSaved * M.seniorHourRate,
      badBefore, badAfter, badRub: (badBefore - badAfter) * badCost,
      daysSaved, tthRub: hires * daysSaved * seatDay,
      agency,
    };
    return { ...res, total: res.hoursRub + res.badRub + res.tthRub + res.agency };
  }, [hires, salary]);
  return (
    <div className="space-y-5">
      <section className="card grid gap-6 md:grid-cols-2" aria-label="Параметры найма">
        <Range id="roi-hires" label="План найма ИТ-специалистов в год" value={hires} min={5} max={200} step={5} onChange={setHires} fmt={(v) => `${v} чел.`} />
        <Range id="roi-salary" label="Средняя вилка" value={salary} min={100_000} max={500_000} step={10_000} onChange={setSalary} fmt={(v) => `${rub(v)}/мес`} />
      </section>
      <section className="rounded-2xl bg-brand-night p-5 text-white sm:p-6" aria-live="polite">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/70">Итог для HRD · в год</p>
        <p className="mt-1 text-3xl font-extrabold tabular-nums">{mln(r.total)}</p>
        <p className="mt-1 text-sm text-white/80">экономии при найме {hires} специалистов со средней вилкой {rub(salary)}</p>
      </section>
      <div className="grid gap-3 sm:grid-cols-2">
        <Kpi label="Часы Senior на техсобеседованиях" value={`−${n0(r.hoursSaved)}${NB}ч`}
          hint={`≈ ${mln(r.hoursRub)}: 3-минутная устная защита кода с видеоаватаром и параметрический тест вместо 8 техинтервью на найм`} />
        <Kpi label="Защита от ошибки найма" value={mln(r.badRub)} tone="ok"
          hint={`«Раздутые» резюме в топ-10: 58${NB}% → 6,9${NB}%. Ошибочных наймов ${r.badBefore.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} → ${r.badAfter.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} в год`} />
        <Kpi label="Скорость закрытия вакансии" value={`42 → 3${NB}дня`}
          hint={`−${r.daysSaved} дней на вакансию; ≈ ${mln(r.tthRub)} выработки, которую не теряет пустое место`} />
        <Kpi label="Без кадровых агентств" value={mln(r.agency)} hint={`Комиссия 20${NB}% годового дохода × ${hires} наймов`} />
      </div>
      <details className="card text-sm text-brand-ink/80">
        <summary className="cursor-pointer font-semibold text-brand-night">Как считаем</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 marker:text-brand">
          <li>Классика: {M.interviewsPerHire} техсобеседований на найм × {M.seniorsPerInterview} Senior × {fmtHours(M.hoursPerInterview)}; «Драфт»: {M.draftFinalists} финалиста × {fmtHours(M.draftHours)}. Час Senior — {rub(M.seniorHourRate)} с налогами.</li>
          <li>Доля «раздутых» резюме в топ-10 — по стенду проверки подборки (58 % у ранжирования по резюме, 6,9 % у «Драфта»); до оффера доходит каждое {Math.round(1 / M.slipToOffer)}-е. Цена ошибки — {M.badHireMonths} месяцев ФОТ × {M.payroll.toLocaleString("ru-RU")} (налоги, адаптация, повторный поиск).</li>
          <li>Срок закрытия вакансии: 42 дня на рынке против 3 дней от подборки до принятия приглашения; день пустого места — месячный ФОТ / 30.</li>
          <li>Агентство: {Math.round(M.agencyFee * 100)} % годового дохода за каждого найденного специалиста.</li>
        </ul>
      </details>
    </div>
  );
}

// ================================================================== 3. Рентген кода (Code DNA & AI-Slop Detector)

const SAMPLES: { id: string; title: string; code: string }[] = [
  {
    id: "gpt", title: "Слепо из нейросети",
    code: `# Here is an optimized and secure implementation of the payment transfer function.
# Мы учитываем принцип аммонита для надёжности перевода.
import redis
import requests

r = redis.Redis()

def transfer(from_id, to_id, amount):
    """This function transfers money between accounts safely."""
    # Step 1: Acquire lock
    with r.atomic_lock(f"acc:{from_id}", timeout=5):
        # Step 2: Check balance
        balance = get_balance(from_id)
        if balance >= amount:
            # Step 3: Perform transfer
            update_balance(from_id, balance - amount)
            update_balance(to_id, get_balance(to_id) + amount)
            # Step 4: Notify user
            requests.post("https://api.example.com/notify", json={"to": to_id}, retries=3)
            return True
    return False`,
  },
  {
    id: "senior", title: "Продакшн Senior",
    code: `from decimal import Decimal
import logging
import psycopg

log = logging.getLogger("payments")

def transfer(conn: psycopg.Connection, idem_key: str, src: int, dst: int, amount: Decimal) -> str:
    if amount <= 0:
        raise ValueError("amount must be positive")
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO transfers (idem_key, src, dst, amount) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (idem_key) DO NOTHING RETURNING id",
            (idem_key, src, dst, amount),
        )
        row = cur.fetchone()
        if row is None:  # повтор запроса — отдаём прежний результат
            return conn.execute("SELECT status FROM transfers WHERE idem_key = %s", (idem_key,)).fetchone()[0]
        # блокируем оба счёта в стабильном порядке — без взаимоблокировок
        a, b = sorted((src, dst))
        conn.execute("SELECT id FROM accounts WHERE id IN (%s, %s) ORDER BY id FOR UPDATE", (a, b))
        upd = conn.execute(
            "UPDATE accounts SET balance = balance - %s WHERE id = %s AND balance >= %s",
            (amount, src, amount),
        )
        if upd.rowcount == 0:
            conn.execute("UPDATE transfers SET status = 'declined' WHERE id = %s", row)
            return "declined"
        conn.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (amount, dst))
        conn.execute("UPDATE transfers SET status = 'done' WHERE id = %s", row)
    log.info("transfer done", extra={"idem_key": idem_key, "src": src, "dst": dst})
    return "done"`,
  },
  {
    id: "junior", title: "Поверхностный Junior",
    code: `balances = {}

def transfer(a, b, amount):
    try:
        if balances[a] > amount:
            balances[a] = balances[a] - amount
            balances[b] = balances[b] + amount
            print("ok")
    except:
        print("error")`,
  },
];

type Kind = "ai" | "hall" | "canary" | "senior" | "junior";
interface Rule { re: RegExp; kind: Kind; label: string; q?: (line: number, src: string) => string }

// Сигналы и вопросы к конкретной строке. Порядок важен: первые сработавшие с вопросом уходят видеоаватару.
const RULES: Rule[] = [
  { re: /аммонит|квокк|ламантин|ammonite|quokka/i, kind: "canary", label: "Канарейка: редкое слово из невидимой ИИ-метки задания",
    q: (l) => `Строка ${l}: в комментарии упомянут «принцип аммонита». Расскажите, что это за принцип и почему он нужен именно здесь?` },
  { re: /\.atomic_lock\(/, kind: "hall", label: "Галлюцинация API: в redis-py нет atomic_lock (есть r.lock)",
    q: (l) => `Строка ${l}: \`r.atomic_lock(...)\` — каким методом redis-py вы на самом деле возьмёте блокировку и что будет, если процесс упадёт, не отпустив её?` },
  { re: /requests\.(get|post|put|patch)\([^)]*retries\s*=/, kind: "hall", label: "Галлюцинация API: у requests нет аргумента retries",
    q: (l) => `Строка ${l}: какой аргумент \`retries\` принимает \`requests.post\`? Как сделать повтор с экспоненциальной задержкой и не отправить уведомление дважды?` },
  { re: /\.to_iso\(\)|asyncio\.run_forever\(/, kind: "hall", label: "Галлюцинация API: несуществующий метод стандартной библиотеки" },
  { re: /#\s*(Step|Шаг)\s*\d/i, kind: "ai", label: "Шаблонные комментарии «Step N»" },
  { re: /Here is|Below is|optimized and secure|This function/i, kind: "ai", label: "Вводные фразы чат-бота в коде" },
  { re: /example\.com/i, kind: "ai", label: "Заглушка example.com в боевом коде" },
  { re: /^\s*if\s+.*balance.*[<>]=?\s*amount/i, kind: "junior", label: "Проверка баланса отдельно от списания — гонка",
    q: (l) => `Строка ${l}: между проверкой баланса и списанием — что произойдёт при двух параллельных запросах на одну и ту же сумму?` },
  { re: /ON CONFLICT/i, kind: "senior", label: "Идемпотентность через ON CONFLICT",
    q: (l) => `Строка ${l}: \`ON CONFLICT (idem_key) DO NOTHING\` — что получит повторный запрос, если первый ещё не закоммичен? Какой уровень изоляции здесь нужен?` },
  { re: /FOR UPDATE/i, kind: "senior", label: "Пессимистичная блокировка строк FOR UPDATE",
    q: (l) => `Строка ${l}: зачем сортировать id перед \`FOR UPDATE\`? Опишите сценарий взаимоблокировки без сортировки.` },
  { re: /WHERE .*balance\s*>=\s*%s/i, kind: "senior", label: "Условное списание в одном UPDATE",
    q: (l) => `Строка ${l}: почему условие \`balance >= %s\` стоит внутри UPDATE, а не в отдельном SELECT перед ним?` },
  { re: /\.transaction\(\)|BEGIN\b|atomic\(\)/, kind: "senior", label: "Явная транзакция" },
  { re: /\bDecimal\b/, kind: "senior", label: "Деньги в Decimal, не во float" },
  { re: /sorted\(\(/, kind: "senior", label: "Стабильный порядок блокировок" },
  { re: /rowcount/, kind: "senior", label: "Проверка числа затронутых строк" },
  { re: /raise ValueError/, kind: "senior", label: "Валидация входа" },
  { re: /log(ger)?\.(info|warning|error)\(.*extra=/, kind: "senior", label: "Структурный лог с контекстом",
    q: (l) => `Строка ${l}: лог пишется после коммита — как не потерять событие для уведомления клиента, если процесс упадёт в этот момент (outbox)?` },
  { re: /def \w+\([^)]*:\s*[\w.]+/, kind: "senior", label: "Аннотации типов" },
  { re: /except\s*:/, kind: "junior", label: "Голый except глотает все ошибки",
    q: (l) => `Строка ${l}: голый \`except:\` — какие ошибки он проглотит и как вы узнаете о сбое в продакшене?` },
  { re: /^\w+\s*=\s*\{\}\s*$/, kind: "junior", label: "Состояние в глобальном словаре",
    q: (l, s) => `Строка ${l}: состояние хранится в глобальном \`${s.trim().split(/\s/)[0]}\` — что с ним станет при двух воркерах и перезапуске сервиса?` },
  { re: /print\(/, kind: "junior", label: "print вместо логирования" },
];

// Стиль кандидата по коду из теста: аннотации типов, комментарии по-русски, Decimal, редкие комментарии, длина строки ≈ 55.
const TEST_STYLE = { hints: 1, ru: 1, density: 0.08, template: 1, len: 55, money: 1 };

interface Xray { ai: number; theta: number; grade: string; style: number; questions: string[]; signals: { line: number; kind: Kind; label: string }[] }

function xray(code: string): Xray {
  const lines = code.split("\n");
  const signals: Xray["signals"] = [];
  const questions: string[] = [];
  RULES.forEach((r) => {
    const i = lines.findIndex((s) => r.re.test(s));
    if (i < 0) return;
    signals.push({ line: i + 1, kind: r.kind, label: r.label });
    if (r.q && questions.length < 3) questions.push(r.q(i + 1, lines[i]));
  });
  const cnt = (k: Kind) => signals.filter((s) => s.kind === k).length;
  const templ = lines.filter((s) => /#\s*(Step|Шаг)\s*\d|Here is|optimized and secure|This function/i.test(s)).length;
  const aiScore = 3 * cnt("canary") + 2.5 * cnt("hall") + Math.min(4, templ) + (signals.some((s) => s.label.includes("example.com")) ? 0.5 : 0);
  const ai = Math.round(Math.min(97, Math.max(3, 100 / (1 + Math.exp(-(aiScore - 3))))));
  const theta = Math.max(-2.5, Math.min(2.5, -0.3 + 0.24 * cnt("senior") - 0.15 * cnt("junior") - 0.35 * cnt("hall")));
  const grade = theta < -1.2 ? "Стажёр" : theta < -0.3 ? "Junior" : theta < 0.8 ? "Middle" : "Senior";

  const comments = lines.filter((s) => /^\s*#|"""|#\s/.test(s));
  const code_ = lines.filter((s) => s.trim());
  const f = {
    hints: /def \w+\([^)]*:\s*[\w.]+/.test(code) ? 1 : 0,
    ru: comments.length ? comments.filter((s) => /[а-яё]/i.test(s)).length / comments.length : 0.5,
    density: code_.length ? comments.length / code_.length : 0,
    template: templ ? 0 : 1,
    len: code_.length ? code_.reduce((s, x) => s + x.length, 0) / code_.length : 0,
    money: /\bDecimal\b/.test(code) ? 1 : 0,
  };
  const sims = [
    1 - Math.abs(f.hints - TEST_STYLE.hints), 1 - Math.abs(f.ru - TEST_STYLE.ru),
    1 - Math.min(1, Math.abs(f.density - TEST_STYLE.density) * 5), 1 - Math.abs(f.template - TEST_STYLE.template),
    1 - Math.min(1, Math.abs(f.len - TEST_STYLE.len) / 40), 1 - Math.abs(f.money - TEST_STYLE.money),
  ];
  const style = Math.round((sims.reduce((s, x) => s + x, 0) / sims.length) * 100);

  // Добираем вопросы до трёх по самым «тяжёлым» строкам кода
  const longest = code_.reduce((b, s) => (s.length > b.length ? s : b), "");
  const fallback = [
    longest && `Строка ${lines.indexOf(longest) + 1}: объясните, что делает эта строка и какой у неё худший случай под нагрузкой 5 000 RPS?`,
    "Назовите три граничных случая, которыми вы покроете эту функцию тестами, и какой из них сейчас упадёт.",
    "Что вы поменяете в этом коде, если сервис запустят в двух дата-центрах одновременно?",
  ].filter(Boolean) as string[];
  for (const q of fallback) if (questions.length < 3) questions.push(q);
  return { ai, theta, grade, style, questions, signals };
}

function CodeDna() {
  const [code, setCode] = useState(SAMPLES[0].code);
  const [sample, setSample] = useState<string | null>(SAMPLES[0].id);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Xray | null>(null);
  function run() {
    if (!code.trim()) return;
    setBusy(true); setRes(null);
    window.setTimeout(() => { setRes(xray(code)); setBusy(false); }, 900);
  }
  const choose = (id: string) => { const s = SAMPLES.find((x) => x.id === id)!; setSample(id); setCode(s.code); setRes(null); };
  const verdict = res && (res.ai >= 60
    ? { kind: "error" as const, t: `Высокий риск слепой ИИ-генерации по эвристике кода (оценка сложности фрагмента: ${res.grade}). Рекомендуем проверить понимание решений на устной защите.` }
    : res.style >= 70
      ? { kind: "ok" as const, t: `Эвристическая оценка фрагмента кода — ${res.grade}, структура соответствует эталонному инженерному профилю (${res.style} %).` }
      : { kind: "info" as const, t: `Явных маркеров чат-бота мало; эвристическая оценка фрагмента — ${res.grade}. Отклонения от эталона структуры (${res.style} %) можно уточнить на собеседовании.` });
  return (
    <div className="space-y-5">
      <section className="card space-y-4" aria-label="Код кандидата">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-brand-night">Код кандидата (эвристический разбор фрагмента)</h2>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Примеры кода">
            {SAMPLES.map((s, i) => (
              <button key={s.id} type="button" onClick={() => choose(s.id)} aria-pressed={sample === s.id}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${sample === s.id ? "bg-brand-night text-white" : "bg-brand-blush/40 text-brand-plum hover:bg-brand-blush/70"}`}>
                {i + 1}. {s.title}
              </button>
            ))}
          </div>
        </div>
        <textarea aria-label="Код для рентгена" className="input min-h-[300px] font-mono text-xs leading-relaxed" spellCheck={false} value={code}
          onChange={(e) => { setCode(e.target.value); setSample(null); setRes(null); }} placeholder="Вставьте любой код кандидата" />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-brand-ink/65">Статическая эвристика в браузере (21 правило: канарейки, галлюцинации API, транзакции, типы): не заменяет адаптивный тест платформы.</p>
          <button type="button" className="btn-primary" onClick={run} disabled={busy || !code.trim()} data-testid="code-xray">
            {busy ? "Просвечиваем…" : "Провести рентген кода"}
          </button>
        </div>
      </section>

      {res && verdict && (
        <section className="card space-y-4" aria-live="polite" aria-label="Результат рентгена">
          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi label="Маркеры ИИ-генерации (эвристика)" value={`${res.ai}${NB}%`} tone={res.ai >= 60 ? "warn" : "ok"} />
            <Kpi label="Оценка по эвристике кода" value={res.grade} hint={`индекс паттернов ${th(res.theta)} (не результат теста)`} />
            <Kpi label="Соответствие эталонному стилю (эвристика)" value={`${res.style}${NB}%`} tone={res.style >= 70 ? "ok" : "warn"} />
          </div>
          <Alert kind={verdict.kind}>{verdict.t}</Alert>
          <div>
            <h3 className="font-bold text-brand-night">3 каверзных вопроса для видеоаватара устной защиты</h3>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-brand-ink/85 marker:font-bold marker:text-brand">
              {res.questions.map((q) => <li key={q}>{q.split("`").map((part, i) => (i % 2
                ? <code key={i} className="rounded bg-brand-blush/40 px-1 py-0.5 font-mono text-[12px] text-brand-plum">{part}</code>
                : part))}</li>)}
            </ol>
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer font-semibold text-brand-night">Найденные сигналы ({res.signals.length})</summary>
            <ul className="mt-2 space-y-1">
              {res.signals.map((s) => (
                <li key={s.label} className="flex gap-2 text-xs">
                  <span className="w-16 shrink-0 font-mono text-brand-ink/55">стр. {s.line}</span>
                  <span className={s.kind === "senior" ? "text-emerald-700" : s.kind === "junior" ? "text-amber-700" : "text-brand"}>{s.label}</span>
                </li>
              ))}
              {!res.signals.length && <li className="text-xs text-brand-ink/65">Явных сигналов нет — оценка по стилю и структуре.</li>}
            </ul>
          </details>
          <p className="text-xs text-brand-ink/60">Вопросы уходят ИИ-аватару вместе с кодом: <Link to="/employer/invitations" className="font-semibold text-brand hover:underline">пригласить кандидата на устную защиту</Link>.</p>
        </section>
      )}
    </div>
  );
}
