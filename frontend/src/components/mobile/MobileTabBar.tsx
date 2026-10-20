// Мобильная нижняя панель навигации кабинетов (телефоны < 768 px, PWA и Android-пакет RuStore).
// Динамически читает разделы роли из sections.ts (или принимает их через пропсы из CabinetLayout),
// выводит 4–5 главных разделов с крупными областями нажатия (≥ 48 px) и лист «Ещё» для остальных разделов.
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { Section } from "../CabinetLayout";
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

// Приоритетные пути для первых вкладок нижней панели (как для текущих sections.ts, так и после укрупнения меню А2).
const PRIMARY_PATHS: Record<string, string[]> = {
  employer: ["", "needs", "candidates", "compare", "search", "invitations", "messages"],
  candidate: ["", "assessment", "feedback", "category", "profile", "invitations", "messages"],
  fsp_analyst: ["", "analytics", "demand", "partners", "trio", "method"],
  expert: ["pairs", "answers", "angoff", "review", "security"],
};

function shortLabel(section: Section, role: string): string {
  const p = section.path;
  if (p === "") return "Обзор";
  if (p === "needs" || p === "vacancies") return "Вакансии";
  if (p === "candidates" || p === "compare" || p === "search" || p === "squad") {
    return role === "employer" ? "Кандидаты" : "Подборки";
  }
  if (p === "assessment" || p === "express") return "Тест";
  if (p === "category" || p === "attempts") return "Грейд";
  if (p === "feedback") return "Навыки";
  if (p === "profile" || p === "fsp") return "Профиль";
  if (p === "invitations") return "Диалоги";
  if (p === "messages") return "Сообщения";
  if (p === "trio") return role === "fsp_analyst" ? "Подтверждение" : "Связь с ФСП";
  if (p === "analytics" || p === "demand" || p === "effect" || p === "salaries" || p === "funnel") return "Аналитика";
  if (p === "partners") return "Партнёры";
  if (p === "method" || p === "security") return "Методика";
  if (p === "company" || p === "tariffs") return "Компания";
  if (p === "ats" || p === "integrations") return "Интеграции";
  if (p === "cups" || p === "assignments" || p === "probes") return "Задания";
  if (p === "mydata" || p === "settings" || p === "notifications" || p === "app") return "Настройки";
  if (p === "pairs") return "Пары";
  if (p === "answers") return "Ответы";
  if (p === "angoff") return "Пороги";
  if (p === "review") return "Очередь";
  const first = section.title.split(/[·—:()]/)[0].trim().split(/\s+/)[0] || section.title;
  return first.length > 11 ? `${first.slice(0, 10)}…` : first;
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
    case "messages":
    case "trio":
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
          <path d="M4 6.5A2.5 2.5 0 016.5 4h11A2.5 2.5 0 0120 6.5v7A2.5 2.5 0 0117.5 16H9l-4.5 3.5V16A2.5 2.5 0 014 13.5v-7z" strokeLinejoin="round" />
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

  const effectiveRole: string = roleProp || me?.role || "candidate";
  const base = baseProp || ROLE_BASE[effectiveRole] || "/candidate";
  const rawSections = sectionsProp || ROLE_SECTIONS[effectiveRole] || candidateSections;

  const visibleSections = useMemo(
    () =>
      rawSections.filter((s) => {
        if (s.flag && !meta?.[s.flag]?.enabled) return false;
        const juryOnly = (s as Section & { juryOnly?: boolean }).juryOnly;
        if (juryOnly && !showJury) return false;
        return true;
      }),
    [rawSections, meta, showJury],
  );

  // Закрывать лист «Ещё» при смене маршрута или по Escape.
  useEffect(() => {
    setSheetOpen(false);
  }, [loc.pathname, loc.search]);

  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSheetOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sheetOpen]);

  // Выбираем 4–5 главных вкладок роли.
  const { primaryTabs, extraTabs } = useMemo(() => {
    if (visibleSections.length <= 5) {
      return { primaryTabs: visibleSections, extraTabs: [] as Section[] };
    }
    const preferred = PRIMARY_PATHS[effectiveRole] || [];
    const chosen: Section[] = [];
    const used = new Set<string>();

    for (const p of preferred) {
      if (chosen.length >= 4) break;
      const hit = visibleSections.find((s) => s.path === p);
      if (hit && !used.has(hit.path)) {
        // Не ставим рядом два однотипных экрана подбора, чтобы оставить место под «Диалоги/Приглашения».
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

    const rest = visibleSections.filter((s) => !used.has(s.path));
    return { primaryTabs: chosen, extraTabs: rest };
  }, [visibleSections, effectiveRole]);

  const hasSeparateMessages = visibleSections.some((s) => s.path === "messages");

  function badgeFor(section: Section): number {
    if (section.path === "messages") return unread;
    if (section.path === "invitations") return hasSeparateMessages ? hiringTodo : hiringTodo + unread;
    return 0;
  }

  function isSectionActive(section: Section): boolean {
    const to = section.path ? `${base}/${section.path}` : base;
    if (section.path === "") return loc.pathname === base || loc.pathname === `${base}/`;
    if (loc.pathname === to || loc.pathname.startsWith(`${to}/`)) return true;
    if (section.also?.some((a) => loc.pathname === `${base}/${a}` || loc.pathname.startsWith(`${base}/${a}/`))) {
      return true;
    }
    return false;
  }

  const activeInExtra = extraTabs.some((s) => isSectionActive(s));
  const extraBadge = extraTabs.reduce((acc, s) => acc + badgeFor(s), 0);

  if (!visibleSections.length) return null;

  return (
    <>
      {/* Отступ в потоке документа на мобильном, чтобы фиксированная панель не перекрывала нижний контент */}
      <div
        className="h-16 md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
        aria-hidden="true"
      />

      {sheetOpen && extraTabs.length > 0 && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-brand-night/50 backdrop-blur-[1px] md:hidden"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setSheetOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Все разделы кабинета"
            data-testid="mobile-tab-sheet"
            className="max-h-[82vh] w-full overflow-y-auto rounded-t-3xl bg-white p-4 pb-6 shadow-2xl"
            style={{ paddingBottom: "calc(1.25rem + env(safe-area-inset-bottom, 0px))" }}
          >
            <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-brand-night/15" aria-hidden="true" />
            <div className="mb-3 flex items-center justify-between px-1">
              <p className="text-sm font-extrabold text-brand-night">Разделы кабинета</p>
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
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {visibleSections.map((s) => {
                const to = s.path ? `${base}/${s.path}` : base;
                const active = isSectionActive(s);
                const badge = badgeFor(s);
                return (
                  <Link
                    key={s.path}
                    to={to}
                    onClick={() => setSheetOpen(false)}
                    className={`flex min-h-[48px] items-center justify-between gap-3 rounded-2xl px-3.5 py-2.5 text-sm transition-colors ${
                      active
                        ? "bg-brand-night font-semibold text-white"
                        : "bg-[#FBF8FC] text-brand-ink hover:bg-brand-blush/30"
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <TabIcon path={s.path} />
                      <div className="min-w-0">
                        <div className="truncate font-semibold">{s.title}</div>
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
                );
              })}
            </div>
          </div>
        </div>
      )}

      <nav
        aria-label="Нижняя навигация кабинета"
        data-testid="mobile-tab-bar"
        className={`fixed inset-x-0 bottom-0 z-40 border-t border-brand-night/10 bg-white/95 backdrop-blur-md md:hidden ${className}`}
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        <div className="mx-auto grid max-w-lg grid-flow-col auto-cols-fr items-stretch px-1">
          {primaryTabs.map((s) => {
            const to = s.path ? `${base}/${s.path}` : base;
            const active = isSectionActive(s);
            const badge = badgeFor(s);
            const label = shortLabel(s, effectiveRole);
            return (
              <Link
                key={s.path}
                to={to}
                data-testid={`mobile-tab-${s.path || "overview"}`}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-[56px] flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-semibold transition-colors ${
                  active ? "text-brand" : "text-brand-ink/70 hover:text-brand-night"
                }`}
              >
                {active && (
                  <span
                    className="absolute inset-x-3 top-0 h-0.5 rounded-b-full bg-brand"
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
                <span className="max-w-full truncate leading-tight">{label}</span>
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
              className={`relative flex min-h-[56px] flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-semibold transition-colors ${
                activeInExtra || sheetOpen ? "text-brand" : "text-brand-ink/70 hover:text-brand-night"
              }`}
            >
              {(activeInExtra || sheetOpen) && (
                <span
                  className="absolute inset-x-3 top-0 h-0.5 rounded-b-full bg-brand"
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
              <span className="max-w-full truncate leading-tight">Ещё</span>
            </button>
          )}
        </div>
      </nav>
    </>
  );
}

export default MobileTabBar;
