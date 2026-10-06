import { api, type TokenOut } from "./api";

export type Persona = "candidate" | "candidate_nofsp" | "employer" | "expert";
export const JURY_DOMAIN = "@jury.example.com";
export const isJury = (email?: string | null) => !!email && email.endsWith(JURY_DOMAIN);
const LOCAL: Record<string, Persona> = { candidate: "candidate", "candidate-nofsp": "candidate_nofsp", employer: "employer", expert: "expert" };
/** Персона по почте демо-учётки: candidate@… (общее демо) или candidate+<песочница>@… */
export const personaOf = (email?: string | null): Persona | null =>
  isJury(email) ? LOCAL[email!.slice(0, -JURY_DOMAIN.length).split("+")[0]] ?? null : null;

// Своя песочница жюри: у каждого эксперта свой набор демо-персон, сброс не мешает другим.
const KEY_SCENARIO = "jury_scenario";
export const scenario = {
  get: () => localStorage.getItem(KEY_SCENARIO),
  set: (s: string | null | undefined) => { if (s) localStorage.setItem(KEY_SCENARIO, s); },
};
type JuryTokenOut = TokenOut & { landing: string; scenario: string | null; shared: boolean; persona: Persona };

const KEY_ON = "jury_guide";
const KEY_HIDDEN = "jury_guide_hidden";
const KEY_STEP = "jury_guide_step";
export const guide = {
  on: () => localStorage.getItem(KEY_ON) === "1",
  enable: () => { localStorage.setItem(KEY_ON, "1"); localStorage.removeItem(KEY_HIDDEN); },
  disable: () => { localStorage.removeItem(KEY_ON); },
  hidden: () => localStorage.getItem(KEY_HIDDEN) === "1",
  hide: () => localStorage.setItem(KEY_HIDDEN, "1"),
  show: () => localStorage.removeItem(KEY_HIDDEN),
  step: () => Number(localStorage.getItem(KEY_STEP) ?? "0") || 0,
  setStep: (n: number) => localStorage.setItem(KEY_STEP, String(n)),
};

/** Токен персоны своей песочницы (первый вход создаёт песочницу; лимит исчерпан — общее демо). */
export async function juryToken(persona: Persona): Promise<JuryTokenOut> {
  const r = await api<JuryTokenOut>("/jury/login", { method: "POST", body: { persona, scenario: scenario.get() ?? "new" }, auth: false });
  scenario.set(r.scenario);
  return r;
}

export async function juryLogin(persona: Persona, signIn: (t: string) => Promise<unknown>): Promise<string> {
  const r = await juryToken(persona);
  await signIn(r.access_token);
  guide.enable();
  // проводник переходит к первому шагу этой роли, если текущий шаг — за другую
  if (STEPS[guide.step()]?.persona !== persona) {
    const i = STEPS.findIndex((s) => s.persona === persona);
    if (i >= 0) guide.setStep(i);
  }
  return r.landing;
}

/** Сброс своей песочницы. Нужен токен демо-персоны: если вход не выполнен — входим в свою песочницу. */
export async function juryReset(email: string | null | undefined, signIn: (t: string) => Promise<unknown>): Promise<{ seconds: number }> {
  if (!isJury(email)) await signIn((await juryToken("candidate")).access_token);
  const r = await api<JuryTokenOut & { seconds: number }>("/jury/reset", { method: "POST" });
  scenario.set(r.scenario);
  await signIn(r.access_token);  // учётки пересозданы — старый токен недействителен
  return r;
}

export interface GuideStep {
  title: string; text: string; path: string; persona: Persona | null; match: RegExp; cta: string;
}

/** Сквозной сценарий из п. 3.3 ТЗ + механики тестирования и подбора. */
export const STEPS: GuideStep[] = [
  { title: "Регистрация соискателя", persona: null, path: "/register?role=candidate", match: /^\/(register|verify)/, cta: "Открыть регистрацию",
    text: "Почта с кодом подтверждения и согласие на обработку данных. Чтобы не ждать письма, следующий шаг откроет готового демо-кандидата — регистрация у него уже пройдена." },
  { title: "Опрос и тест", persona: "candidate", path: "/candidate/assessment", match: /^\/candidate\/assessment/, cta: "Войти как кандидат",
    text: "Опрос пройден, тест сдан настоящим адаптивным движком: 8–16 заданий из банка 128 семейств, у каждого свой вариант, 3 контрольных задания-«канарейки». Для жюри снято правило 90 дней: тест можно пройти заново и посмотреть, как интерфейс фиксирует уход со вкладки и вставку текста." },
  { title: "Присвоение категории", persona: "candidate", path: "/candidate/category", match: /^\/candidate\/category/, cta: "Открыть категорию",
    text: "Категория «Backend · Middle» и место в рейтинге. Рейтинг строится только на подтверждённом: тест (T1) и достижения ФСП из реестра (T2). Нет истории ФСП — нейтрально, без штрафа." },
  { title: "Работодатель: потребность", persona: "employer", path: "/employer/needs", match: /^\/employer\/needs/, cta: "Войти как работодатель",
    text: "Потребность пишется своими словами — система выделяет направление, грейд, стек и зарплату («260 000 ₽ на руки», «от 200 до 250 тыс.»). Подборка объясняет каждого кандидата по каждому требованию." },
  { title: "Поиск по категории", persona: "employer", path: "/employer/search", match: /^\/employer\/(search|candidates)/, cta: "Открыть поиск",
    text: "Поиск по категории «направление · грейд». В карточке — уровни доказанности T0/T1/T2 и «достоверность результата» теста с причинами. ФИО и контакты скрыты до согласия кандидата." },
  { title: "Выход на контакт", persona: "employer", path: "/employer/invitations", match: /^\/employer\/(invitations|probes)/, cta: "Приглашения работодателя",
    text: "Приглашение-оффер с обязательной вилкой «от–до» в рублях. Пригласите Марию Королёву (кандидат с ФСП) из подборки или поиска; Илье Сергееву приглашение уже отправлено." },
  { title: "Ответ кандидата", persona: "candidate_nofsp", path: "/candidate/invitations", match: /^\/candidate\/invitations/, cta: "Войти как кандидат без ФСП",
    text: "Кандидат видит компанию, вилку и доказательства, по которым его выбрали. После «Принять» работодатель получает контакты — и только тогда." },
  { title: "Эксперт: проверка ответов", persona: "expert", path: "/expert", match: /^\/expert/, cta: "Войти как эксперт",
    text: "Развёрнутые ответы, которые не смог оценить LLM, ждут эксперта: критерии рубрики с весами, эталоны сильного и слабого ответа. Оценка сразу пересчитывает результат теста." },
  { title: "Как мы проверяем себя", persona: null, path: "/validation", match: /^\/validation/, cta: "Открыть /validation",
    text: "Метрики теста и подбора, как они получились, и «Красная кнопка»: атаки, которые вы запускаете сами — раздуть резюме, сменить имя, добавить фальшивый значок ФСП, «слить» часть банка." },
];
