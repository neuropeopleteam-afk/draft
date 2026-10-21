import type { Section } from "../../components/CabinetLayout";

// А2 (TASK_A2.md): целевая навигация кабинета кандидата — 6 пунктов левого меню («Обзор» + 5 разделов)
// со вкладками внутри объединённых разделов. Все прежние адреса продолжают работать.
export const candidateSections: Section[] = [
  {
    path: "profile",
    title: "Профиль и паспорт",
    description: "Резюме с обезличиванием (152-ФЗ), стек, контакты и подтверждение достижений по протоколам ФСП.",
    tabs: [
      { path: "profile", title: "Профиль и резюме" },
      { path: "fsp", title: "Паспорт ФСП и протоколы" },
    ],
  },
  {
    path: "assessment",
    title: "Тест и грейд",
    description: "Адаптивный тест на грейд, текущая категория, сравнение попыток, устная защита и карта навыков.",
    also: ["express", "interview"],
    tabs: [
      { path: "assessment", title: "Пройти тест" },
      { path: "category", title: "Категория и паспорт" },
      { path: "attempts", title: "Попытки и устная защита" },
      { path: "feedback", title: "Карта навыков и спрос" },
    ],
  },
  {
    path: "invitations",
    title: "Приглашения и вакансии",
    description: "Входящие приглашения с вилкой, встречные условия «Да, если…», открытые вакансии и переписка.",
    tabs: [
      { path: "invitations", title: "Приглашения" },
      { path: "vacancies", title: "Вакансии" },
      { path: "messages", title: "Переписка" },
    ],
  },
  {
    path: "probes",
    title: "Задания и кубки",
    description: "Задания с вилкой от работодателей, практические задачи с автопроверкой и кубки в вашей категории.",
    tabs: [
      { path: "probes", title: "Задания с вилкой" },
      { path: "assignments", title: "Задания с автопроверкой" },
      { path: "cups", title: "Кубки и соревнования" },
    ],
  },
  {
    path: "settings",
    title: "Настройки и данные",
    description: "Приватность карточки, скрытый минимум зарплаты, выгрузка и отзыв согласий (152-ФЗ), связь с ФСП.",
    also: ["app"],
    tabs: [
      { path: "settings", title: "Приватность и интересы" },
      { path: "mydata", title: "Мои данные и согласия" },
      { path: "trio", title: "Связь с ФСП" },
      { path: "notifications", title: "Уведомления" },
    ],
  },
];
