// Разделы кабинета эксперта (меню CabinetLayout). Отдельно от экранов (Panel.tsx): App.tsx грузит экраны лениво (Я16).
export const panelSections = [
  { path: "pairs", title: "A · Пары", description: "Соответствие кандидата потребности" },
  { path: "answers", title: "B · Ответы", description: "Оценка ответов по рубрике" },
  { path: "angoff", title: "C · Пороги грейдов", description: "Метод Ангоффа" },
  { path: "review", title: "Очередь проверки", description: "Ответы кандидатов на проверке" },
  { path: "security", title: "Безопасность входа", description: "Второй фактор: код из приложения-аутентификатора" },
];
