/** Палитра брендбука Федерации спортивного программирования (ФСП): электрический индиго #402FFF, графит #0E1126 и благородный алый акцент #EC1D35. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#402FFF",
          // фон под белым текстом (кнопки, бейджи): #3322E8 — 6,1 : 1, при наведении #2416BA — 8,2 : 1 (AAA/AA для 14 px)
          strong: "#3322E8",
          deep: "#2416BA",
          soft: "#5B4BFF",
          blush: "#ECEFFE",
          lavender: "#5E6494",
          plum: "#1E244D",
          night: "#0E1126",
          ink: "#131629",
          crimson: "#EC1D35",
        },
      },
      // Высокий контраст AA на светлом фоне для мелких подписей и ссылок в единой гамме ФСП
      textColor: { brand: { DEFAULT: "#3120E0", lavender: "#4A5080" } },
      fontFamily: {
        sans: ["Montserrat", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      maxWidth: { content: "72rem" },
    },
  },
  plugins: [],
};
