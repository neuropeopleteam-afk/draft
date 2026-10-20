// Маршрут Елены по кабинетам. Шаг — экран; у шага несколько «битов»: на каждую короткую реплику — свой блок экрана
// (подсветка) и, если нужно, «нажатие» в нужный момент реплики. Тексты реплик — на сервере
// (/api/interview/concierge/script → beats, порядок совпадает с битами здесь; один источник, голос из кэша).
import { api } from "../../lib/api";
import type { Persona } from "../../lib/jury";

export type TourTrack = "all" | "candidate" | "employer" | "fsp";
export type Cabinet = "candidate" | "employer" | "fsp" | "public";

export interface Beat {
  /** Что подсветить: первый видимый из списка через запятую; «text:Надпись» — кнопка или ссылка с такой надписью. */
  target?: string;
  /** Что «нажать» во время реплики и когда (доля реплики 0…1). */
  click?: string;
  clickAt?: number;
}

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
  /** Главный блок экрана: его ждём при открытии. */
  selector: string;
  beats: Beat[];
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

const H1 = "main h1";

export const STEPS: Record<string, TourStep> = {
  "cand-overview": {
    id: "cand-overview", cabinet: "candidate", persona: "candidate", path: "/candidate", match: /^\/candidate\/?$/,
    selector: "[data-tour='cand-roadmap'], main h1",
    beats: [
      { target: H1 },
      { target: "[data-tour='cand-roadmap']" },
      { target: "[data-testid='interest-card'], [data-tour='cand-roadmap']" },
      { target: "[data-testid='candidate-salary-tools'], [data-tour='cand-roadmap']" },
      { target: "[data-tour='cand-step-2-btn']", click: "[data-tour='cand-step-2-btn']", clickAt: 0.8 },
    ],
  },
  "cand-assessment": {
    id: "cand-assessment", cabinet: "candidate", persona: "candidate", path: "/candidate/assessment",
    selector: "[data-testid='grade-cards'], [data-testid='test-launch-box'], main h1",
    beats: [
      { target: "[data-testid='grade-cards'], main h1", click: "[data-testid='grade-cards'] button:nth-child(4)", clickAt: 0.75 },
      { target: "[data-testid='grade-hint'], [data-testid='grade-cards']" },
      { target: "[data-testid='mode-choice'], [data-testid='test-launch-box']" },
      { target: "[data-testid='test-launch-box'], [data-testid='mode-choice']" },
    ],
  },
  "cand-category": {
    id: "cand-category", cabinet: "candidate", persona: "candidate", path: "/candidate/category",
    selector: "[data-testid='theta-scale'], #passport, main h1",
    beats: [
      { target: "[data-testid='theta-scale'], main h1" },
      { target: "#passport, [data-testid='theta-scale']" },
    ],
  },
  "cand-defense": {
    id: "cand-defense", cabinet: "candidate", persona: "candidate", path: "/candidate/attempts",
    selector: "[data-testid='integrity-badge'], main h1",
    beats: [
      { target: "[data-testid='integrity-badge'], main h1" },
      { target: "[data-testid='live-defense'], [data-testid='defense-panel'], [data-testid='integrity-defense-start'], main h1" },
    ],
  },
  "cand-feedback": {
    id: "cand-feedback", cabinet: "candidate", persona: "candidate", path: "/candidate/feedback",
    selector: "[data-testid='route-source'], main h1",
    beats: [
      { target: "[data-testid='route-source'], main h1" },
      { target: "[data-testid='hh-market-skills'], [data-testid='route-source']" },
    ],
  },
  "cand-invitations": {
    id: "cand-invitations", cabinet: "candidate", persona: "candidate", path: "/candidate/invitations",
    selector: "main h1",
    beats: [
      { target: H1 },
      { target: "main li, main article, main .card, main h1" },
    ],
  },
  "emp-home": {
    id: "emp-home", cabinet: "employer", persona: "employer", path: "/employer", match: /^\/employer\/?$/,
    selector: "[data-testid='invites-left'], main h1",
    beats: [
      { target: "[data-testid='invites-left'], main h1" },
      { target: "[data-testid='employer-squad-card'], main h1" },
    ],
  },
  "emp-needs": {
    id: "emp-needs", cabinet: "employer", persona: "employer", path: "/employer/needs", match: /^\/employer\/needs\/?$/,
    selector: "[data-tour='emp-roadmap'], #need, main h1",
    beats: [
      { target: "[data-tour='emp-roadmap'], #need" },
      { target: "#need, [data-testid='sample-need']", click: "[data-testid='sample-need']", clickAt: 0.45 },
      { target: "text:Разобрать требования, #need" },
    ],
  },
  "emp-compare": {
    id: "emp-compare", cabinet: "employer", persona: "employer", path: "/employer/compare",
    resolve: () => latestNeedPath("/compare"), match: /^\/employer\/needs\/[^/]+\/compare/,
    selector: "[data-testid='decision-proof-strip'], [data-testid='compare-scroll'], main h1",
    beats: [
      { target: "[data-testid='decision-proof-strip'], [data-testid='compare-scroll'], main h1" },
      { target: "[data-testid='exec-advisor'], [data-testid='compare-scroll'], main h1" },
    ],
  },
  "emp-squad": {
    id: "emp-squad", cabinet: "employer", persona: "employer", path: "/employer/squad",
    selector: "main h1",
    beats: [
      { target: H1 },
      { target: "[data-testid='squad-batch-offer'], main h1" },
    ],
  },
  "emp-invitations": {
    id: "emp-invitations", cabinet: "employer", persona: "employer", path: "/employer/invitations",
    selector: "[data-testid='invites-left'], main h1",
    beats: [
      { target: "[data-testid='invites-left'], main h1" },
      { target: "[data-testid='ats-transfer-potok'], main h1" },
    ],
  },
  "emp-ats": {
    id: "emp-ats", cabinet: "employer", persona: "employer", path: "/employer/ats",
    selector: "[data-testid='ats-live-check'], main h1",
    beats: [{ target: "[data-testid='ats-live-check'], main h1" }],
  },
  "fsp-cabinet": {
    id: "fsp-cabinet", cabinet: "fsp", persona: "fsp", path: "/fsp", match: /^\/fsp\/?$/,
    selector: "main h1",
    beats: [
      { target: H1 },
      { target: "[data-testid='fsp-rank-converter'], main h1" },
      { target: "a[href='/fsp/effect']", click: "a[href='/fsp/effect']", clickAt: 0.8 },
    ],
  },
  "fsp-effect": {
    id: "fsp-effect", cabinet: "fsp", persona: "fsp", path: "/fsp/effect",
    selector: "main h1",
    beats: [{ target: H1 }],
  },
  "warroom": {
    id: "warroom", cabinet: "public", persona: null, path: "/warroom",
    selector: "main h1",
    beats: [
      { target: H1 },
      { target: "[data-testid='wr-tab-arch'], main h1" },
      { target: "[data-testid='wr-tab-cheat'], main h1", click: "[data-testid='wr-tab-cheat']", clickAt: 0.25 },
    ],
  },
  "val-arena": {
    id: "val-arena", cabinet: "public", persona: null, path: "/validation",
    selector: "[data-testid='validation-headline'], main h1",
    beats: [
      { target: "[data-testid='validation-headline'], #headline, main h1" },
      { target: "[data-testid='matching-arena'], main h1" },
      { target: "[data-testid='matching-arena'], main h1", click: "[data-testid='arena-tab-grade']", clickAt: 0.12 },
    ],
  },
};

export const TRACKS: Record<TourTrack, string[]> = {
  candidate: ["cand-overview", "cand-assessment", "cand-category", "cand-defense", "cand-feedback", "cand-invitations"],
  employer: ["emp-home", "emp-needs", "emp-compare", "emp-squad", "emp-invitations", "emp-ats"],
  fsp: ["fsp-cabinet", "fsp-effect"],
  all: ["cand-overview", "cand-assessment", "cand-category", "cand-defense", "cand-feedback", "emp-needs", "emp-compare",
    "emp-squad", "emp-invitations", "fsp-cabinet", "fsp-effect", "warroom", "val-arena"],
};

/** Совместимость со старым API: плоский список шагов. */
export const TOUR_STEPS: TourStep[] = Object.values(STEPS);
