/** Палитра шаблона ЛЦТ; брендбук ФСП подключим, когда придёт. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#FF0053",
          soft: "#FC3777",
          blush: "#FFD6E4",
          lavender: "#8A83D1",
          plum: "#520978",
          night: "#310F53",
          ink: "#1C1D22",
        },
      },
      // Текст цветами палитры на белом: lavender #8A83D1 — 3,4 : 1, brand #FF0053 — 3,9 : 1, ниже AA для мелких
      // подписей и ссылок. Для текста — те же оттенки чуть темнее (5,6 : 1 и 4,9 : 1); фоны, кнопки, рамки
      // и графики остаются в исходных цветах палитры ЛЦТ.
      textColor: { brand: { DEFAULT: "#E0004C", lavender: "#5F57B8" } },
      fontFamily: { sans: ["Montserrat", "system-ui", "sans-serif"] },
      maxWidth: { content: "72rem" },
    },
  },
  plugins: [],
};
