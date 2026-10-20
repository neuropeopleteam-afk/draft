// Маршрут Насти по кабинетам: каждый пункт меню каждого кабинета — отдельный шаг (экран). У шага несколько «битов»:
// на каждую короткую реплику — свой блок экрана (подсветка) и, если нужно, «нажатие» в нужный момент реплики.
// Тексты реплик — на сервере (/api/interview/concierge/script → beats, порядок совпадает с битами здесь; один
// источник, голос из кэша). Списки меню — pages/candidate/sections.ts, pages/employer/sections.ts,
// ideas/fsp/sections.ts: при изменении меню шаги меняются вместе с ними.
import { api } from "../../lib/api";
import type { Persona } from "../../lib/jury";

export type TourTrack = "all" | "candidate" | "employer" | "fsp";
export type Cabinet = "home" | "candidate" | "employer" | "fsp" | "public";

export interface Beat {
  /** Что подсветить: первый видимый из списка через запятую; «text:Надпись» — кнопка или ссылка с такой надписью. */
  target?: string;
  /** Что «нажать» во время реплики и когда (доля реплики 0…1). */
  click?: string;
  clickAt?: number;
  /** Реплика-переход: «нажатие» открывает этот шаг. Звучит, только если он следующий в обзоре
   *  (при показе одного экрана — пропускается, иначе Настя «открыла и замолчала»). */
  lead?: string;
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

/** Простой экран кабинета: один главный блок (заголовок) и реплики по нему. */
function plain(id: string, cabinet: Cabinet, persona: Persona | null, path: string, beats: Beat[] = [{ target: H1 }], selector = H1): TourStep {
  return { id, cabinet, persona, path, selector, beats: beats.length ? beats : [{ target: H1 }] };
}

export const STEPS: Record<string, TourStep> = {
  // ---------------------------------------------------------------- главная
  "home": {
    id: "home", cabinet: "home", persona: null, path: "/", match: /^\/$/,
    selector: "main h1, h1",
    beats: [{ target: "main h1, h1" }, { target: "text:Работодателям, text:Как это работает, main h1, h1" }],
  },

  // ---------------------------------------------------------------- кандидат
  "cand-overview": {
    id: "cand-overview", cabinet: "candidate", persona: "candidate", path: "/candidate", match: /^\/candidate\/?$/,
    selector: "[data-tour='cand-roadmap'], main h1",
    beats: [
      { target: H1 },
      { target: "[data-tour='cand-roadmap']" },
      { target: "[data-testid='interest-card'], [data-tour='cand-roadmap']" },
      { target: "[data-testid='candidate-salary-tools'], [data-tour='cand-roadmap']" },
      { target: "[data-tour='cand-step-2-btn']", click: "[data-tour='cand-step-2-btn']", clickAt: 0.8, lead: "cand-assessment" },
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
      { target: "text:История грейда, text:Две специализации, main h1" },
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
      { target: "[data-testid='route-source'], text:Карта навыков по темам, main h1" },
      { target: "[data-testid='hh-market-skills'], text:Что требуют работодатели, [data-testid='route-source']" },
      { target: "text:Маршрут роста, text:Соревнования ФСП, main h1" },
    ],
  },
  "cand-profile": plain("cand-profile", "candidate", "candidate", "/candidate/profile", [
    { target: "text:Контакты, text:Резюме, main h1" },
    { target: "text:Как вас видит работодатель, main h1" },
  ]),
  "cand-invitations": {
    id: "cand-invitations", cabinet: "candidate", persona: "candidate", path: "/candidate/invitations",
    selector: "main h1",
    beats: [
      { target: H1 },
      { target: "main li, main article, main .card, main h1" },
    ],
  },
  "cand-messages": plain("cand-messages", "candidate", "candidate", "/candidate/messages", [{ target: H1 }, { target: "main li, main article, main h1" }]),
  "cand-trio": plain("cand-trio", "candidate", "candidate", "/candidate/trio", [
    { target: H1 },
    { target: "text:Подключить представителя ФСП, main h1" },
  ]),
  "cand-cups": plain("cand-cups", "candidate", "candidate", "/candidate/cups", [
    { target: "text:Кубки работодателей, main h1" },
    { target: "text:Таблица результатов, text:Мой результат, main h1" },
  ]),
  "cand-fsp": plain("cand-fsp", "candidate", "candidate", "/candidate/fsp", [
    { target: "[data-testid='fsp-identity-link'], [data-testid='button-fsp-registry-sync'], main h1" },
    { target: "text:Индекс достижений ФСП, text:Достижения, main h1" },
  ]),
  "cand-mydata": plain("cand-mydata", "candidate", "candidate", "/candidate/mydata", [
    { target: "[data-testid='mydata-stored'], [data-testid='my-data'], main h1" },
    { target: "[data-testid='mydata-download'], [data-testid='mydata-contacts'], [data-testid='my-data'], main h1" },
  ]),
  "cand-probes": plain("cand-probes", "candidate", "candidate", "/candidate/probes"),
  "cand-assignments": plain("cand-assignments", "candidate", "candidate", "/candidate/assignments", [
    { target: H1 },
    { target: "text:Свежесть профиля, text:Как часто предлагать, main h1" },
  ]),
  "cand-settings": plain("cand-settings", "candidate", "candidate", "/candidate/settings", [
    { target: "text:Поля обезличенной карточки, main h1" },
    { target: "text:Скрытый минимум зарплаты, text:Согласия, main h1" },
  ]),
  "cand-vacancies": plain("cand-vacancies", "candidate", "candidate", "/candidate/vacancies"),
  "cand-notifications": plain("cand-notifications", "candidate", "candidate", "/candidate/notifications", [
    { target: "text:Каналы, main h1" },
    { target: "text:Лента, main h1" },
  ]),

  // ---------------------------------------------------------------- работодатель
  "emp-home": {
    id: "emp-home", cabinet: "employer", persona: "employer", path: "/employer", match: /^\/employer\/?$/,
    selector: "[data-testid='invites-left'], [data-testid='company-tariff'], main h1",
    beats: [
      { target: "[data-testid='invites-left'], [data-testid='company-tariff'], main h1" },
      { target: "[data-testid='employer-squad-card'], main h1" },
      { target: "text:С чего начать, main h1" },
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
      { target: "[data-testid='code-xray'], main h1" },
    ],
  },
  "emp-search": plain("emp-search", "employer", "employer", "/employer/search", [
    { target: "main form, main [role='search'], main h1" },
    { target: "main li, main article, main table, main h1" },
  ]),
  "emp-invitations": {
    id: "emp-invitations", cabinet: "employer", persona: "employer", path: "/employer/invitations",
    selector: "[data-testid='invites-left'], main h1",
    beats: [
      { target: "[data-testid='invites-left'], main h1" },
      { target: "[data-testid='ats-transfer-potok'], main h1" },
    ],
  },
  "emp-messages": plain("emp-messages", "employer", "employer", "/employer/messages"),
  "emp-trio": plain("emp-trio", "employer", "employer", "/employer/trio"),
  "emp-ats": {
    id: "emp-ats", cabinet: "employer", persona: "employer", path: "/employer/ats",
    selector: "[data-testid='ats-live-check'], main h1",
    beats: [
      { target: "[data-testid='ats-live-check'], main h1" },
      { target: "text:Этапы из «Потока», text:Журнал передач, main h1" },
    ],
  },
  "emp-cups": plain("emp-cups", "employer", "employer", "/employer/cups", [
    { target: H1 },
    { target: "text:Таблица результатов, text:Решения — оценка вслепую, main h1" },
  ]),
  "emp-company": plain("emp-company", "employer", "employer", "/employer/company", [
    { target: "[data-testid='company-tariff'], main h1" },
  ]),
  "emp-probes": plain("emp-probes", "employer", "employer", "/employer/probes", [{ target: "[data-testid='probes-need-filter'], main h1" }]),
  "emp-assignments": plain("emp-assignments", "employer", "employer", "/employer/assignments", [
    { target: "text:Состав задания, main h1" },
    { target: "text:Отправить кандидатам, text:Кандидаты, main h1" },
  ]),
  "emp-vacancies": plain("emp-vacancies", "employer", "employer", "/employer/vacancies"),
  "emp-notifications": plain("emp-notifications", "employer", "employer", "/employer/notifications", [{ target: "text:Каналы, text:Лента, main h1" }]),
  "emp-tariffs": plain("emp-tariffs", "employer", "employer", "/employer/tariffs", [
    { target: "[data-testid='tariff-left'], main h1" },
    { target: "text:Стать партнёром ФСП, text:Партнёрам ФСП, main h1" },
  ]),

  // ---------------------------------------------------------------- Федерация
  "fsp-cabinet": {
    id: "fsp-cabinet", cabinet: "fsp", persona: "fsp", path: "/fsp", match: /^\/fsp\/?$/,
    selector: "main h1",
    beats: [
      { target: "text:Главное за период, main h1" },
      { target: "text:ФСП и приглашения, main h1" },
      { target: "text:Воронка кандидатов, text:Офферы против рынка, main h1" },
      { target: "[data-testid='fsp-rank-converter'], main h1" },
      { target: "a[href='/fsp/demand'], a[href='/fsp/effect']", click: "a[href='/fsp/demand']", clickAt: 0.8, lead: "fsp-demand" },
    ],
  },
  "fsp-demand": plain("fsp-demand", "fsp", "fsp", "/fsp/demand", [{ target: H1 }, { target: "main table, main svg, main h1" }]),
  "fsp-effect": plain("fsp-effect", "fsp", "fsp", "/fsp/effect", [{ target: H1 }, { target: "main table, main svg, main h1" }]),
  "fsp-salaries": plain("fsp-salaries", "fsp", "fsp", "/fsp/salaries", [{ target: H1 }, { target: "main table, main svg, main h1" }]),
  "fsp-funnel": plain("fsp-funnel", "fsp", "fsp", "/fsp/funnel", [{ target: H1 }, { target: "main table, main svg, main h1" }]),
  "fsp-cups": plain("fsp-cups", "fsp", "fsp", "/fsp/cups", [{ target: H1 }]),
  "fsp-trio": plain("fsp-trio", "fsp", "fsp", "/fsp/trio", [{ target: H1 }]),
  "fsp-method": plain("fsp-method", "fsp", "fsp", "/fsp/method", [{ target: H1 }, { target: "text:Доступ, main a[download], main h1" }]),
  "fsp-security": plain("fsp-security", "fsp", "fsp", "/fsp/security", [{ target: "[data-testid='twofa-state'], text:Состояние второго фактора, main h1" }]),
  // «Польза» и «Партнёры» видны в меню, когда на сервере включены тарифы (на стенде — включены)
  "fsp-benefit": plain("fsp-benefit", "fsp", "fsp", "/fsp/benefit", [{ target: "text:По регионам, main h1" }, { target: "text:По направлениям, text:Вклад партнёров ФСП, main h1" }]),
  "fsp-partners": plain("fsp-partners", "fsp", "fsp", "/fsp/partners", [{ target: "text:Заявки компаний, text:Партнёры, main h1" }]),

  // ---------------------------------------------------------------- для жюри и общие страницы
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
  "pricing": plain("pricing", "public", null, "/pricing", [{ target: "main h1, h1" }, { target: "text:Как платформа зарабатывает, main h1, h1" }], "main h1, h1"),
  "install": plain("install", "public", null, "/install", [{ target: "main h1, h1" }], "main h1, h1"),
};

/** Пункты меню кабинетов по порядку (основные, затем «Ещё»). */
export const TRACKS: Record<TourTrack, string[]> = {
  candidate: ["cand-overview", "cand-assessment", "cand-category", "cand-defense", "cand-feedback", "cand-profile", "cand-invitations",
    "cand-messages", "cand-trio", "cand-cups", "cand-fsp", "cand-mydata",
    "cand-probes", "cand-assignments", "cand-settings", "cand-vacancies", "cand-notifications"],
  employer: ["emp-home", "emp-needs", "emp-compare", "emp-squad", "emp-search", "emp-invitations", "emp-messages", "emp-trio", "emp-ats",
    "emp-cups", "emp-company", "emp-probes", "emp-assignments", "emp-vacancies", "emp-notifications", "emp-tariffs"],
  fsp: ["fsp-cabinet", "fsp-demand", "fsp-effect", "fsp-salaries", "fsp-funnel", "fsp-cups", "fsp-benefit", "fsp-partners", "fsp-trio",
    "fsp-method", "fsp-security"],
  // весь сайт — основные пункты меню каждого кабинета (без «Ещё») и раздел для технического жюри
  all: ["home",
    "cand-overview", "cand-assessment", "cand-category", "cand-defense", "cand-feedback", "cand-profile", "cand-invitations",
    "cand-messages", "cand-trio", "cand-cups", "cand-fsp", "cand-mydata",
    "emp-home", "emp-needs", "emp-compare", "emp-squad", "emp-search", "emp-invitations", "emp-messages", "emp-trio", "emp-ats", "emp-cups",
    "fsp-cabinet", "fsp-demand", "fsp-effect", "fsp-salaries", "fsp-funnel", "fsp-cups", "fsp-benefit", "fsp-partners", "fsp-trio",
    "fsp-method", "fsp-security",
    "warroom", "val-arena"],
};

/** Совместимость со старым API: плоский список шагов. */
export const TOUR_STEPS: TourStep[] = Object.values(STEPS);
