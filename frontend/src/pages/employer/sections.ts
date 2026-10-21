import type { Section } from "../../components/CabinetLayout";

// А2 (TASK_A2.md): целевая навигация кабинета работодателя — 7 пунктов левого меню («Обзор» + 6 разделов)
// со вкладками внутри объединённых разделов. Все прежние адреса продолжают работать.
export const employerSections: Section[] = [
  {
    path: "needs",
    title: "Потребности и вакансии",
    description: "Описание потребностей, ранжированные подборки, публикация вакансий и подписки на категории.",
    tabs: [
      { path: "needs", title: "Потребности и подборки" },
      { path: "vacancies", title: "Наши вакансии" },
      { path: "notifications", title: "Подписки и уведомления" },
    ],
  },
  {
    path: "search",
    title: "Подбор кандидатов",
    description: "Поиск по подтверждённым грейдам и стеку, табличное сравнение кандидатов и Командный Драфт ФСП.",
    also: ["candidates", "mutual"],
    tabs: [
      { path: "search", title: "Поиск и подборка" },
      { path: "compare", title: "Сравнение кандидатов" },
      { path: "squad", title: "Командный Драфт" },
    ],
  },
  {
    path: "invitations",
    title: "Приглашения и отклики",
    description: "Отправленные приглашения с вилкой зарплаты, встречные условия кандидатов и переписка.",
    tabs: [
      { path: "invitations", title: "Приглашения" },
      { path: "messages", title: "Сообщения и отклики" },
    ],
  },
  {
    path: "probes",
    title: "Задания и кубки",
    description: "Короткие задания с вилкой, практические задания с автопроверкой и отборочные кубки.",
    tabs: [
      { path: "probes", title: "Задания с вилкой" },
      { path: "assignments", title: "Практические задания" },
      { path: "cups", title: "Кубки и турниры" },
    ],
  },
  {
    path: "trio",
    title: "Связь с ФСП",
    description: "Трёхсторонний канал: работодатель, кандидат и представитель ФСП — проверка достижений и условий оффера.",
  },
  {
    path: "company",
    title: "Компания, ATS и тариф",
    description: "Профиль организации, индекс доверия ЕГРЮЛ, интеграция с ATS и управление тарифом.",
    also: ["app"],
    tabs: [
      { path: "company", title: "Профиль компании" },
      { path: "ats", title: "Интеграция с ATS" },
      { path: "tariffs", title: "Тарифы", flag: "tariffs" },
    ],
  },
];
