import type { ReactNode } from "react";

/** Числа в таблицах /validation — по правому краю (А21): ячейка-число — строка, начинающаяся с цифры/знака, или «—». */
export const isNumCell = (c: ReactNode): boolean =>
  typeof c === "number" || (typeof c === "string" && /^[\s−\-+±≈~<>≤≥]*(\d|—\s*$)/.test(c));

/** Столбец числовой, если все его непустые ячейки — числа (первый столбец — подписи строк, всегда влево). */
export const numCol = (rows: ReactNode[][], j: number): boolean =>
  j > 0 && rows.length > 0 && rows.some((r) => r[j] != null && r[j] !== "") && rows.every((r) => r[j] == null || r[j] === "" || isNumCell(r[j]));
