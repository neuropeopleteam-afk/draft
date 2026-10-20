// Маршрут Елены по кабинетам — сразу в нужный кабинет, без показа главной страницы (замечание владельца 20.10).
// Тексты реплик — на сервере (/api/interview/concierge/script: один источник, голос из кэша), здесь — экраны,
// что подсветить и что «нажать» в нужный момент реплики.
import { api } from "../../lib/api";
import type { Persona } from "../../lib/jury";

export type TourTrack = "all" | "candidate" | "employer" | "fsp";
export type Cabinet = "candidate" | "employer" | "fsp" | "validation";

export interface TourStep {
  id: string;
  cabinet: Cabinet;
  /** Демо-персона экрана; null — публичная страница. */
  persona: Persona | null;
  /** Куда перейти (resolve — если адрес зависит от данных). */
  path: string;
  resolve?: () => Promise<string | null>;
  /** Какие адреса считаются этим экраном (после переадресаций и перехода по «нажатию» прошлого шага). */
  match?: RegExp;
  /** Что подсветить: первый видимый из списка через запятую. */
  selector: string;
  /** Что «нажать» во время реплики и когда (доля реплики 0…1). */
  click?: string;
  clickAt?: number;
}

async function latestNeedPath(suffix = ""): Promise<string | null> {
  try {
    const needs = (await api<{ id: string; versions?: { total?: number; version?: number }[] }[]>("/employer/needs")) ?? [];
    const last = <T,>(a?: T[]): T | undefined => (a && a.length ? a[a.length - 1] : undefined);
    const pick = needs.slice().reverse().find((n) => (last(n.versions)?.total ?? 0) >= 2) ?? last(needs);
    if (!pick) return null;
    const v = last(pick.versions)?.version;
    return `/employer/needs/${pick.id}${suffix}${suffix && v ? `?v=${v}` : ""}`;
  } catch {
    return null;
  }
}

export const STEPS: Record<string, TourStep> = {
  "cand-overview": {
    id: "cand-overview", cabinet: "candidate", persona: "candidate", path: "/candidate", match: /^\/candidate\/?$/,
    selector: "[data-tour='cand-roadmap']", click: "[data-tour='cand-step-2-btn']", clickAt: 0.93,
  },
  "cand-assessment": {
    id: "cand-assessment", cabinet: "candidate", persona: "candidate", path: "/candidate/assessment",
    selector: "[data-testid='grade-cards'], [data-testid='test-launch-box']",
    click: "[data-testid='grade-cards'] button:nth-child(4)", clickAt: 0.3,
  },
  "cand-feedback": {
    id: "cand-feedback", cabinet: "candidate", persona: "candidate", path: "/candidate/feedback",
    selector: "[data-testid='theta-scale'], [data-testid='route-source'], main h1",
  },
  "cand-passport": {
    id: "cand-passport", cabinet: "candidate", persona: "candidate", path: "/candidate/attempts",
    selector: "[data-testid='integrity-badge'], main h1",
  },
  "cand-defense": {
    id: "cand-defense", cabinet: "candidate", persona: "candidate", path: "/candidate/attempts",
    selector: "[data-testid='live-defense'], [data-testid='defense-panel'], [data-testid='integrity-defense-start'], main h1",
  },
  "cand-invitations": {
    id: "cand-invitations", cabinet: "candidate", persona: "candidate", path: "/candidate/invitations",
    selector: "main .card, main h1",
  },
  "emp-needs": {
    id: "emp-needs", cabinet: "employer", persona: "employer", path: "/employer/needs", match: /^\/employer\/needs\/?$/,
    selector: "#need, [data-tour='emp-roadmap']", click: "[data-testid='sample-need']", clickAt: 0.42,
  },
  "emp-compare": {
    id: "emp-compare", cabinet: "employer", persona: "employer", path: "/employer/compare",
    resolve: () => latestNeedPath("/compare"), match: /^\/employer\/needs\/[^/]+\/compare/,
    selector: "[data-testid='decision-proof-strip'], [data-testid='compare-scroll'], main h1",
  },
  "fsp-cabinet": {
    id: "fsp-cabinet", cabinet: "fsp", persona: "fsp", path: "/fsp", match: /^\/fsp\/?$/,
    selector: "main .card, main h1", click: "a[href='/fsp/effect']", clickAt: 0.94,
  },
  "val-arena": {
    id: "val-arena", cabinet: "validation", persona: null, path: "/validation",
    selector: "[data-testid='matching-arena'], #headline, main h1", click: "[data-testid='arena-tab-grade']", clickAt: 0.62,
  },
};

export const TRACKS: Record<TourTrack, string[]> = {
  candidate: ["cand-overview", "cand-assessment", "cand-feedback", "cand-passport", "cand-defense", "cand-invitations"],
  employer: ["emp-needs", "emp-compare"],
  fsp: ["fsp-cabinet"],
  all: ["cand-overview", "cand-assessment", "cand-feedback", "cand-defense", "emp-needs", "emp-compare", "fsp-cabinet", "val-arena"],
};

/** Совместимость со старым API (startAvatarTour, тесты): плоский список шагов. */
export const TOUR_STEPS: TourStep[] = Object.values(STEPS);

export function trackFor(stepId: string, current: TourTrack | null): TourTrack {
  if (current && TRACKS[current].includes(stepId)) return current;
  const c = STEPS[stepId]?.cabinet;
  return c === "candidate" ? "candidate" : c === "employer" ? "employer" : c === "fsp" ? "fsp" : "all";
}
