import { GRADES, GRADE_TITLE_ALL } from "../components/ui";
import { useMeta, type Meta } from "./meta";

/** Уровни платформы снизу вверх для направления. Без флага GRADES_EXT_ENABLED — четыре (как GRADES); с флагом —
 * плюс Lead/Principal там, где в банке есть их проверенные семейства. Без направления — уровни, видимые хотя бы
 * в одном направлении (фильтры поиска, списки). */
export function gradeIds(meta: Meta | null | undefined, direction?: string | null): string[] {
  const ext = meta?.grades_ext;
  if (!ext?.enabled) return Object.keys(GRADES);
  const byDir = ext.by_direction ?? {};
  if (direction && byDir[direction]) return byDir[direction].grades;
  const any = new Set(Object.values(byDir).flatMap((x) => x.grades));
  return ext.grades.filter((g) => g in GRADES || any.has(g));
}

export function gradeMap(ids: string[]): Record<string, string> {
  return Object.fromEntries(ids.map((g) => [g, GRADE_TITLE_ALL[g] ?? g]));
}

/** id → подпись уровней для направления (порядок — снизу вверх). */
export function useGrades(direction?: string | null): Record<string, string> {
  return gradeMap(gradeIds(useMeta(), direction));
}
