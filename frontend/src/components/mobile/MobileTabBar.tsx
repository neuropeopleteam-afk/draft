// Мобильная нижняя панель навигации кабинетов (телефоны < 768 px, PWA и Android-пакет RuStore).
// Поддерживает обновлённое меню кабинетов волны 1 (7 разделов у работодателя, 6 у кандидата, 5 у ФСП):
// выводит 4 главные вкладки роли с короткими подписями без дублей и кнопку «Ещё» для остальных разделов и вложенных вкладок.
// При монтировании на мобильном экране (< 768 px) выставляет на document.documentElement переменную
// --mobile-tabbar-h = "<высота_nav_в_px>px" (через getBoundingClientRect + ResizeObserver, и "0px" на >= 768 px),
// чтобы плавающая кнопка и окно ИИ-проводника Насти смещались выше панели и не перекрывали вкладки.
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router-dom";
import type { Section, SubTab } from "../CabinetLayout";
import { useAuth } from "../../lib/auth";
import { type Role } from "../../lib/api";
import { useMeta } from "../../lib/meta";
import { candidateSections } from "../../pages/candidate/sections";
import { employerSections } from "../../pages/employer/sections";
import { fspSections } from "../../ideas/fsp/sections";
import { panelSections } from "../../pages/expert/sections";

export interface MobileTabBarProps {
  role?: Role;
  sections?: Section[];
  base?: string;
  unread?: number;
  hiringTodo?: number;
  showJury?: boolean;
  onOpenMenu?: () => void;
  className?: string;
}

const ROLE_BASE: Record<string, string> = {
  candidate: "/candidate",
  employer: "/employer",
  fsp_analyst: "/fsp",
  expert: "/expert",
  admin: "/fsp",
};

const ROLE_SECTIONS: Record<string, Section[]> = {
  candidate: candidateSections,
  employer: employerSections,
  fsp_analyst: fspSections,
  expert: panelSections,
  admin: fspSections,
};

const OVERVIEW_SECTION: Section = {
  path: "",
  title: "Обзор",
  description: "Сводка кабинета, ключевые показатели и быстрые действия.",
};

// Приоритетные пути первых 4 вкладок для каждой роли под структуру меню 7 / 6 / 5:
// - работодатель (7 пунктов): Обзор | Подборки | Подбор | Приглашения + Ещё (Задания и кубки, Связь с ФСП, Компания/ATS/тариф)
// - кандидат (6 пунктов): Обзор | Профиль | Тест | Приглашения + Ещё (Задания и кубки, Настройки и данные)
// - ФСП (5 пунктов): Обзор | Спрос | Кубки | Связь + Ещё (Безопасность и профиль)
// - эксперт (6 пунктов): Обзор | Очередь | Пары | Ответы + Ещё (Пороги грейдов, Безопасность входа)
const PRIMARY_PATHS: Record<string, string[]> = {
  employer: ["", "needs", "search", "invitations", "candidates", "compare", "messages", "probes", "trio", "company"],
  candidate: ["", "profile", "assessment", "invitations", "feedback", "category", "messages", "probes", "settings"],
  fsp_analyst: ["", "demand", "cups", "trio", "analytics", "effect", "partners", "method", "security"],
  admin: ["", "demand", "cups", "trio", "analytics", "effect", "partners", "method", "security"],
  expert: ["", "review", "pairs", "answers", "angoff", "security"],
};

// Точные короткие подписи вкладок по ролям и путям без коллизий:
// все подписи <= 11 символов, чтобы на экране 360 px 5 кнопок (4 вкладки + «Ещё») помещались без усечения.
const ROLE_LABELS: Record<string, Record<string, string>> = {
  employer: {
    "": "Обзор",
    needs: "Подборки",
    vacancies: "Вакансии",
    candidates: "Кандидаты",
    compare: "Сравнение",
    search: "Подбор",
    squad: "Команда",
    invitations: "Приглашения",
    messages: "Сообщения",
    trio: "Связь с ФСП",
    cups: "Кубки",
    probes: "Задания",
    assignments: "Практика",
    ats: "Интеграции",
    integrations: "Интеграции",
    company: "Компания",
    tariffs: "Тарифы",
    notifications: "Уведомления",
    app: "Приложение",
  },
  candidate: {
    "": "Обзор",
    invitations: "Приглашения",
    assessment: "Тест",
    express: "Экспресс",
    feedback: "Навыки",
    category: "Грейд",
    attempts: "Попытки",
    profile: "Профиль",
    fsp: "Паспорт ФСП",
    messages: "Сообщения",
    trio: "Связь с ФСП",
    cups: "Кубки",
    assignments: "Практика",
    probes: "Задания",
    vacancies: "Вакансии",
    mydata: "Мои данные",
    settings: "Настройки",
    notifications: "Уведомления",
    app: "Приложение",
  },
  fsp_analyst: {
    "": "Обзор",
    analytics: "Аналитика",
    demand: "Спрос",
    effect: "Эффект",
    salaries: "Зарплаты",
    funnel: "Воронки",
    cups: "Кубки",
    benefit: "Польза",
    partners: "Партнёры",
    trio: "Связь",
    method: "Методика",
    security: "Безопасность",
  },
  expert: {
    "": "Обзор",
    pairs: "Пары",
    answers: "Ответы",
    angoff: "Пороги",
    review: "Очередь",
    security: "Безопасность",
  },
};

export function shortLabel(section: Section & { short?: string }, role: string): string {
  if (section.short && section.short.trim()) return section.short.trim();
  const roleMap = ROLE_LABELS[role] || ROLE_LABELS[role === "admin" ? "fsp_analyst" : "candidate"] || {};
  const mapped = roleMap[section.path];
  if (mapped) return mapped;
  const cleaned = section.title.replace(/^[A-ZА-Я]\s*·\s*/, "").trim();
  const first = cleaned.split(/[·—:()]/)[0].trim().split(/\s+/)[0] || cleaned;
  return first.length > 12 ? `${first.slice(0, 11)}…` : first;
}

function sectionPaths(section: Section): string[] {
  const paths = [section.path, ...(section.also ?? []), ...(section.tabs?.map((t) => t.path) ?? [])];
  return Array.from(new Set(paths));
}

function TabIcon({ path }: { path: string }) {
  const cls = "h-5 w-5 shrink-0";
  switch (path) {
    case "":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M4 10.5L12 4l8 6.5V19a1 1 0 01-1 1h-4.5v-5.5h-5V20H5a1 1 0 01-1-1v-8.5z" strokeLinejoin="round" />
        </svg>
      );
    case "needs":
    case "vacancies":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <rect x="3.5" y="7" width="17" height="13" rx="2" />
          <path d="M9 7V5.5A1.5 1.5 0 0110.5 4h3A1.5 1.5 0 0115 5.5V7M3.5 12h17" strokeLinecap="round" />
        </svg>
      );
    case "candidates":
    case "compare":
    case "search":
    case "squad":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <circle cx="9" cy="8.5" r="3.2" />
          <path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" strokeLinecap="round" />
          <circle cx="16.5" cy="9.5" r="2.3" />
          <path d="M15.5 14.5c2.3.3 4 1.8 4 4.2" strokeLinecap="round" />
        </svg>
      );
    case "assessment":
    case "express":
    case "category":
    case "attempts":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M12 3l7 3v5.5c0 4.5-3 8.3-7 9.5-4-1.2-7-5-7-9.5V6l7-3z" strokeLinejoin="round" />
          <path d="M8.8 12.2l2.2 2.2 4.4-4.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "feedback":
    case "analytics":
    case "demand":
    case "effect":
    case "salaries":
    case "funnel":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M5 19V11M10 19V6M15 19v-8M20 19V4" strokeLinecap="round" />
        </svg>
      );
    case "profile":
    case "fsp":
    case "company":
    case "partners":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <circle cx="12" cy="8.5" r="3.5" />
          <path d="M5 19.5c0-3.3 3.1-5.5 7-5.5s7 2.2 7 5.5" strokeLinecap="round" />
        </svg>
      );
    case "invitations":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2.5" />
          <path d="M4 7l8 6 8-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "probes":
    case "assignments":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M9 5H6a2 2 0 00-2 2v11a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-3" strokeLinecap="round" />
          <rect x="9" y="3.5" width="6" height="3.5" rx="1" />
          <path d="M8.5 12.5l2.2 2.2 4.8-4.7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "cups":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M7 4h10v5a5 5 0 01-10 0V4z" strokeLinejoin="round" />
          <path d="M7 6H4.5a2 2 0 000 4c1 0 2 .6 2.5 1.5M17 6h2.5a2 2 0 010 4c-1 0-2 .6-2.5 1.5M12 14v4M8.5 20h7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "messages":
    case "trio":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M4 6.5A2.5 2.5 0 016.5 4h11A2.5 2.5 0 0120 6.5v7A2.5 2.5 0 0117.5 16H9l-4.5 3.5V16A2.5 2.5 0 014 13.5v-7z" strokeLinejoin="round" />
        </svg>
      );
    case "settings":
    case "mydata":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M18 6l-1.6 1.6M7.6 16.4L6 18" strokeLinecap="round" />
        </svg>
      );
    case "security":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <rect x="5" y="11" width="14" height="9" rx="2" />
          <path d="M8 11V7a4 4 0 018 0v4" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
          <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
          <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
          <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
        </svg>
      );
  }
}

export function MobileTabBar({
  role: roleProp,
  sections: sectionsProp,
  base: baseProp,
  unread = 0,
  hiringTodo = 0,
  showJury = false,
  onOpenMenu,
  className = "",
}: MobileTabBarProps = {}) {
  const { me } = useAuth();
  const meta = useMeta();
  const loc = useLocation();
  const [sheetOpen, setSheetOpen] = useState(false);
  const sheetRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);

  const effectiveRole: string = roleProp || me?.role || "candidate";
  const base = baseProp || ROLE_BASE[effectiveRole] || "/candidate";
  const rawSections = sectionsProp || ROLE_SECTIONS[effectiveRole] || candidateSections;

  // В CabinetLayout пункт «Обзор» (base) рендерится отдельно перед массивом sections.
  // Для полной навигации 7/6/5 на телефоне гарантируем наличие стартового пункта «Обзор» (path === "").
  const visibleSections = useMemo(() => {
    const filtered = rawSections.filter((s) => {
      if (s.flag && !meta?.[s.flag]?.enabled) return false;
      const juryOnly = (s as Section & { juryOnly?: boolean }).juryOnly;
      if (juryOnly && !showJury) return false;
      return true;
    });
    if (!filtered.length) return [];
    const hasOverview = filtered.some((s) => s.path === "");
    return hasOverview ? filtered : [OVERVIEW_SECTION, ...filtered];
  }, [rawSections, meta, showJury]);

  // Закрывать лист «Ещё» при смене маршрута.
  useEffect(() => {
    setSheetOpen(false);
  }, [loc.pathname, loc.search]);

  // Управление фокусом, Escape и блокировкой прокрутки body при открытом листе «Ещё».
  useEffect(() => {
    if (!sheetOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sheetRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSheetOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [sheetOpen]);

  // Выставляем CSS-переменную --mobile-tabbar-h на documentElement в пикселях (фактическая высота nav с учётом safe-area),
  // когда панель видна (< 768 px), и "0px" на >= 768 px или при размонтировании.
  useEffect(() => {
    if (typeof window === "undefined" || !visibleSections.length) return;
    const root = document.documentElement;
    const mq = window.matchMedia("(max-width: 767px)");
    const sync = () => {
      if (!mq.matches || !navRef.current) {
        root.style.setProperty("--mobile-tabbar-h", "0px");
        return;
      }
      const h = Math.round(navRef.current.getBoundingClientRect().height);
      root.style.setProperty("--mobile-tabbar-h", h > 0 ? `${h}px` : "0px");
    };
    sync();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(sync) : null;
    if (ro && navRef.current) ro.observe(navRef.current);
    mq.addEventListener?.("change", sync);
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);
    return () => {
      ro?.disconnect();
      mq.removeEventListener?.("change", sync);
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
      root.style.setProperty("--mobile-tabbar-h", "0px");
    };
  }, [visibleSections.length]);

  // Выбираем 4 главные вкладки роли, а остальные разделы (из меню 7/6/5) отправляем в кнопку «Ещё».
  // Гарантируем отсутствие дублей подписей.
  const { primaryTabs, extraTabs, tabLabels } = useMemo(() => {
    const pickTabs = (): { primary: Section[]; extra: Section[] } => {
      if (visibleSections.length <= 4) {
        return { primary: visibleSections, extra: [] };
      }
      const preferred = PRIMARY_PATHS[effectiveRole] || PRIMARY_PATHS.candidate;
      const chosen: Section[] = [];
      const used = new Set<string>();

      for (const p of preferred) {
        if (chosen.length >= 4) break;
        const hit = visibleSections.find((s) => s.path === p);
        if (hit && !used.has(hit.path)) {
          const isCandGroup = ["candidates", "compare", "search", "squad"].includes(hit.path);
          const alreadyHasCandGroup = chosen.some((c) => ["candidates", "compare", "search", "squad"].includes(c.path));
          if (isCandGroup && alreadyHasCandGroup) continue;
          chosen.push(hit);
          used.add(hit.path);
        }
      }

      for (const s of visibleSections) {
        if (chosen.length >= 4) break;
        if (!used.has(s.path)) {
          chosen.push(s);
          used.add(s.path);
        }
      }

      chosen.sort((a, b) => {
        if (a.path === "") return -1;
        if (b.path === "") return 1;
        return visibleSections.indexOf(a) - visibleSections.indexOf(b);
      });

      const rest = visibleSections.filter((s) => !used.has(s.path));
      return { primary: chosen, extra: rest };
    };

    const { primary, extra } = pickTabs();
    const seenLabels = new Set<string>();
    const labels = new Map<string, string>();
    for (const s of primary) {
      let lbl = shortLabel(s, effectiveRole);
      if (seenLabels.has(lbl)) {
        lbl = s.title.length > 12 ? `${s.title.slice(0, 11)}…` : s.title;
      }
      seenLabels.add(lbl);
      labels.set(s.path, lbl);
    }
    return { primaryTabs: primary, extraTabs: extra, tabLabels: labels };
  }, [visibleSections, effectiveRole]);

  const hasSeparateMessages = visibleSections.some((s) => s.path === "messages");

  function badgeFor(section: Section): number {
    const ps = sectionPaths(section);
    let b = 0;
    if (ps.includes("invitations")) b += hiringTodo;
    if (ps.includes("messages") && (!hasSeparateMessages || section.path === "messages")) b += unread;
    return b;
  }

  function isSectionActive(section: Section): boolean {
    if (section.path === "") {
      return loc.pathname === base || loc.pathname === `${base}/`;
    }
    return sectionPaths(section).some(
      (p) => p !== "" && (loc.pathname === `${base}/${p}` || loc.pathname.startsWith(`${base}/${p}/`)),
    );
  }

  function visibleSubTabs(section: Section): SubTab[] {
    return (section.tabs ?? []).filter((t) => !t.flag || !!meta?.[t.flag]?.enabled);
  }

  const activeInExtra = extraTabs.some((s) => isSectionActive(s));
  const extraBadge = extraTabs.reduce((acc, s) => acc + badgeFor(s), 0);
  const appLink = effectiveRole === "candidate" || effectiveRole === "employer" ? `${base}/app` : "/install";

  if (!visibleSections.length) return null;

  const fixedLayer = (
    <>
      {sheetOpen && extraTabs.length > 0 && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-brand-night/50 backdrop-blur-[1px] md:hidden"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSheetOpen(false);
          }}
        >
          <div
            ref={sheetRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="Все разделы кабинета"
            data-testid="mobile-tab-sheet"
            className="max-h-[84vh] w-full overflow-y-auto rounded-t-3xl bg-white p-4 pb-6 shadow-2xl outline-none"
            style={{ paddingBottom: "calc(1.25rem + env(safe-area-inset-bottom, 0px))" }}
          >
            <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-brand-night/15" aria-hidden="true" />
            <div className="mb-3 flex items-center justify-between px-1">
              <div>
                <p className="text-sm font-extrabold text-brand-night">Разделы кабинета ({visibleSections.length})</p>
                <p className="text-xs text-brand-ink/60">Быстрый переход к разделам и внутренним вкладкам</p>
              </div>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                aria-label="Закрыть меню разделов"
                className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-brand-ink/65 hover:bg-brand-blush/30"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            {extraTabs.length > 0 && (
              <div className="mb-3">
                <p className="mb-1.5 px-1 text-[11px] font-bold uppercase tracking-[0.12em] text-brand-plum">
                  Остальные разделы ({extraTabs.length})
                </p>
                <div className="grid grid-cols-1 gap-1.5">
                  {extraTabs.map((s) => {
                    const to = s.path ? `${base}/${s.path}` : base;
                    const active = isSectionActive(s);
                    const badge = badgeFor(s);
                    const subTabs = visibleSubTabs(s);
                    return (
                      <div
                        key={`extra-${s.path}`}
                        className={`rounded-2xl border p-2.5 transition-colors ${
                          active
                            ? "border-brand-night bg-brand-night text-white"
                            : "border-brand-night/10 bg-[#F4F6FC] text-brand-ink"
                        }`}
                      >
                        <Link
                          to={to}
                          data-testid={`mobile-sheet-section-${s.path || "overview"}`}
                          onClick={() => setSheetOpen(false)}
                          className="flex min-h-[44px] items-center justify-between gap-3 px-1"
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <TabIcon path={s.path} />
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold">{s.title}</div>
                              {s.description && (
                                <div className={`truncate text-xs ${active ? "text-white/75" : "text-brand-ink/60"}`}>
                                  {s.description}
                                </div>
                              )}
                            </div>
                          </div>
                          {badge > 0 && (
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${
                                active ? "bg-white text-brand-night" : "bg-brand text-white"
                              }`}
                            >
                              {badge}
                            </span>
                          )}
                        </Link>
                        {subTabs.length > 1 && (
                          <div className="mt-2 flex flex-wrap gap-1.5 border-t border-current/10 pt-2">
                            {subTabs.map((t) => {
                              const subTo = `${base}/${t.path}`;
                              const subOn = loc.pathname === subTo || loc.pathname.startsWith(`${subTo}/`);
                              return (
                                <Link
                                  key={t.path}
                                  to={subTo}
                                  onClick={() => setSheetOpen(false)}
                                  className={`inline-flex min-h-[36px] items-center rounded-xl px-2.5 py-1 text-xs font-semibold transition ${
                                    subOn
                                      ? active
                                        ? "bg-white text-brand-night"
                                        : "bg-brand text-white"
                                      : active
                                        ? "bg-white/15 text-white hover:bg-white/25"
                                        : "bg-white text-brand-night ring-1 ring-brand-night/10 hover:bg-brand-blush/40"
                                  }`}
                                >
                                  {t.title}
                                </Link>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div>
              <p className="mb-1.5 px-1 text-[11px] font-bold uppercase tracking-[0.12em] text-brand-ink/55">
                Главные разделы ({primaryTabs.length})
              </p>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {primaryTabs.map((s) => {
                  const to = s.path ? `${base}/${s.path}` : base;
                  const active = isSectionActive(s);
                  const badge = badgeFor(s);
                  const subTabs = visibleSubTabs(s);
                  return (
                    <div
                      key={`all-${s.path || "overview"}`}
                      className={`rounded-2xl border p-2.5 transition-colors ${
                        active
                          ? "border-brand-night bg-brand-night text-white"
                          : "border-brand-night/10 bg-[#F4F6FC] text-brand-ink"
                      }`}
                    >
                      <Link
                        to={to}
                        data-testid={`mobile-sheet-section-${s.path || "overview"}`}
                        onClick={() => setSheetOpen(false)}
                        className="flex min-h-[44px] items-center justify-between gap-3 px-1"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <TabIcon path={s.path} />
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold">{s.title}</div>
                            {s.description && (
                              <div className={`truncate text-xs ${active ? "text-white/75" : "text-brand-ink/60"}`}>
                                {s.description}
                              </div>
                            )}
                          </div>
                        </div>
                        {badge > 0 && (
                          <span
                            className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${
                              active ? "bg-white text-brand-night" : "bg-brand text-white"
                            }`}
                          >
                            {badge}
                          </span>
                        )}
                      </Link>
                      {subTabs.length > 1 && (
                        <div className="mt-2 flex flex-wrap gap-1.5 border-t border-current/10 pt-2">
                          {subTabs.map((t) => {
                            const subTo = `${base}/${t.path}`;
                            const subOn = loc.pathname === subTo || loc.pathname.startsWith(`${subTo}/`);
                            return (
                              <Link
                                key={t.path}
                                to={subTo}
                                onClick={() => setSheetOpen(false)}
                                className={`inline-flex min-h-[36px] items-center rounded-xl px-2.5 py-1 text-xs font-semibold transition ${
                                  subOn
                                    ? active
                                      ? "bg-white text-brand-night"
                                      : "bg-brand text-white"
                                    : active
                                      ? "bg-white/15 text-white hover:bg-white/25"
                                      : "bg-white text-brand-night ring-1 ring-brand-night/10 hover:bg-brand-blush/40"
                                }`}
                              >
                                {t.title}
                              </Link>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-brand-night/10 pt-3">
              <Link
                to={appLink}
                onClick={() => setSheetOpen(false)}
                data-testid="mobile-sheet-install-app"
                className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-brand-blush/50 px-3.5 py-2 text-xs font-bold text-brand-plum hover:bg-brand-blush"
              >
                Приложение и уведомления
              </Link>
              <Link
                to="/support"
                onClick={() => setSheetOpen(false)}
                className="inline-flex min-h-[44px] items-center px-3 py-2 text-xs font-semibold text-brand-ink/70 hover:text-brand-night"
              >
                Помощь и поддержка
              </Link>
            </div>
          </div>
        </div>
      )}

      <nav
        ref={navRef}
        aria-label="Нижняя навигация кабинета"
        data-testid="mobile-tab-bar"
        className={`fixed inset-x-0 bottom-0 z-40 border-t border-[#A59DFF]/25 bg-[#090B1A]/95 text-white shadow-[0_-12px_32px_rgba(9,11,26,0.45)] backdrop-blur-xl md:hidden ${className}`}
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        <div className="mx-auto flex max-w-lg items-stretch justify-between px-1">
          {primaryTabs.map((s) => {
            const to = s.path ? `${base}/${s.path}` : base;
            const active = isSectionActive(s);
            const badge = badgeFor(s);
            const label = tabLabels.get(s.path) || shortLabel(s, effectiveRole);
            return (
              <Link
                key={s.path || "overview"}
                to={to}
                data-testid={`mobile-tab-${s.path || "overview"}`}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[9.5px] font-semibold tracking-[-0.03em] transition-colors ${
                  active ? "text-white" : "text-[#C8CEFF]/75 hover:text-white"
                }`}
              >
                {active && (
                  <span
                    className="absolute inset-x-2 top-0 h-0.5 rounded-b-full bg-[#6557FF] shadow-[0_0_10px_#6557FF]"
                    aria-hidden="true"
                  />
                )}
                <span className="relative flex items-center justify-center">
                  <TabIcon path={s.path} />
                  {badge > 0 && (
                    <span
                      className="absolute -right-2.5 -top-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-brand px-1 text-[10px] font-extrabold leading-none text-white"
                      aria-label={`Непрочитанных: ${badge}`}
                    >
                      {badge > 99 ? "99+" : badge}
                    </span>
                  )}
                </span>
                <span className="whitespace-nowrap leading-tight">{label}</span>
              </Link>
            );
          })}

          {extraTabs.length > 0 && (
            <button
              type="button"
              data-testid="mobile-tab-more"
              aria-expanded={sheetOpen}
              aria-haspopup="dialog"
              onClick={() => {
                setSheetOpen((v) => !v);
                onOpenMenu?.();
              }}
              className={`relative flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[9.5px] font-semibold tracking-[-0.03em] transition-colors ${
                activeInExtra || sheetOpen ? "text-white" : "text-[#C8CEFF]/75 hover:text-white"
              }`}
            >
              {(activeInExtra || sheetOpen) && (
                <span
                  className="absolute inset-x-2 top-0 h-0.5 rounded-b-full bg-[#6557FF] shadow-[0_0_10px_#6557FF]"
                  aria-hidden="true"
                />
              )}
              <span className="relative flex items-center justify-center">
                <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
                  <circle cx="5.5" cy="12" r="1.6" fill="currentColor" />
                  <circle cx="12" cy="12" r="1.6" fill="currentColor" />
                  <circle cx="18.5" cy="12" r="1.6" fill="currentColor" />
                </svg>
                {extraBadge > 0 && (
                  <span
                    className="absolute -right-2.5 -top-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-brand px-1 text-[10px] font-extrabold leading-none text-white"
                    aria-label={`Новых уведомлений: ${extraBadge}`}
                  >
                    {extraBadge > 99 ? "99+" : extraBadge}
                  </span>
                )}
              </span>
              <span className="whitespace-nowrap leading-tight">Ещё</span>
            </button>
          )}
        </div>
      </nav>
    </>
  );

  return (
    <>
      {/* Отступ в потоке документа на мобильном: calc(4rem + safe-area) не схлопывается при box-sizing: border-box */}
      <div
        className="w-full shrink-0 md:hidden"
        style={{ height: "calc(4rem + env(safe-area-inset-bottom, 0px))" }}
        aria-hidden="true"
      />
      {typeof document !== "undefined" ? createPortal(fixedLayer, document.body) : fixedLayer}
    </>
  );
}

export default MobileTabBar;
