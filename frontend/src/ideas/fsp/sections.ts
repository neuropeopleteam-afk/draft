import type { Section } from "../../components/CabinetLayout";

export const fspSections: Section[] = [
  { path: "demand", title: "Спрос работодателей", description: "Категории и навыки: потребности, приглашения, предложение кандидатов." },
  { path: "effect", title: "Эффект соревнований ФСП", description: "Какие дисциплины, разряды и результаты ФСП ведут к приглашениям." },
  { path: "salaries", title: "Зарплаты из офферов", description: "Реальные вилки из приглашений против рынка категории." },
  { path: "funnel", title: "Воронки", description: "Соревнование → приглашение → принятие." },
  { path: "cups", title: "Кубки работодателей", description: "Кубки на платформе как мероприятия: участники, места, приглашения." },
  { path: "benefit", title: "Польза для ФСП", description: "Приглашения и наймы участников ФСП по регионам и направлениям, вклад партнёров, доля с ФСП-бонусом.", flag: "tariffs" },
  { path: "partners", title: "Партнёры ФСП", description: "Метка «Партнёр ФСП» компаниям из спонсорского пакета: заявки, выдача и снятие.", flag: "tariffs" },
  { path: "method", title: "Методика и выгрузки", description: "Правила обезличивания, источники, CSV." },
  { path: "security", title: "Безопасность входа", description: "Второй фактор: код из приложения-аутентификатора (TOTP)." },
];
