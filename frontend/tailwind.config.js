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
      fontFamily: { sans: ["Montserrat", "system-ui", "sans-serif"] },
      maxWidth: { content: "72rem" },
    },
  },
  plugins: [],
};
