import type { Section } from "../../components/CabinetLayout";

export const employerSections: Section[] = [
  { path: "company", title: "Профиль компании", description: "Описание организации и контакты для кандидатов." },
  { path: "needs", title: "Потребности и подборки", description: "Потребность текстом → требования → подборка с объяснениями; версии подборок." },
  { path: "search", title: "Поиск по базе", description: "Фильтры по специализации, грейду, категории, стеку и паспорту ФСП." },
  { path: "probes", title: "Зонды", description: "Короткая задача кандидату с вилкой зарплаты до раскрытия контактов." },
  { path: "cups", title: "Кубки", description: "Соревнование в категории на базе зонда: сроки, таблица результатов, приглашения лучшим с вилкой." },
  { path: "invitations", title: "Приглашения", description: "Офферы с вилкой «от–до», статусы и история." },
  { path: "vacancies", title: "Вакансии", description: "Публикация вакансий и работа с откликами — дополнительный сценарий." },
  { path: "ats", title: "Интеграция с ATS", description: "Хантфлоу API v2, вебхук с подписью HMAC, экспорт карточки в JSON, тестовая ATS." },
  { path: "app", title: "Приложение и уведомления", description: "Установка на главный экран (PWA) и push-уведомления о принятых приглашениях и откликах." },
];
