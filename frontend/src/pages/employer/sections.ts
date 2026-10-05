import type { Section } from "../../components/CabinetLayout";

export const employerSections: Section[] = [
  { path: "company", title: "Профиль компании", description: "Описание организации и контакты для кандидатов." },
  { path: "needs", title: "Потребности и подборки", description: "Потребность текстом → требования → подборка с объяснениями; версии подборок." },
  { path: "search", title: "Поиск по базе", description: "Фильтры по специализации, грейду, категории, стеку и паспорту ФСП." },
  { path: "probes", title: "Зонды", description: "Короткая задача кандидату с вилкой зарплаты до раскрытия контактов." },
  { path: "invitations", title: "Приглашения", description: "Офферы с вилкой «от–до», статусы и история." },
  { path: "vacancies", title: "Вакансии", description: "Публикация вакансий и работа с откликами — дополнительный сценарий.", day: "9–10 октября" },
];
