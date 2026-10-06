import type { Section } from "../../components/CabinetLayout";

export const fspSections: Section[] = [
  { path: "demand", title: "Спрос работодателей", description: "Категории и навыки: потребности, приглашения, предложение кандидатов." },
  { path: "effect", title: "Эффект соревнований ФСП", description: "Какие дисциплины, разряды и результаты ФСП ведут к приглашениям." },
  { path: "salaries", title: "Зарплаты из офферов", description: "Реальные вилки из приглашений против рынка категории." },
  { path: "funnel", title: "Воронки", description: "Соревнование → приглашение → принятие." },
  { path: "cups", title: "Кубки работодателей", description: "Кубки на платформе как мероприятия: участники, места, приглашения." },
  { path: "method", title: "Методика и выгрузки", description: "Правила обезличивания, источники, CSV." },
];
