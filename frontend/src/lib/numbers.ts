/**
 * Единый типизированный источник цифр проекта «Драфт» (читает frontend/src/data/numbers.json,
 * синхронизируемый из docs/NUMBERS.json скриптом tools/publish/gen_numbers.py).
 */
import rawNumbers from "../data/numbers.json";

export interface CiMetric {
  mean: number;
  lo: number;
  hi: number;
}

export interface LandingCardMetric {
  id: string;
  eyebrow: string;
  value: string;
  accent: string;
  subtext: string;
  recompute: string;
  code_ref: string;
  /** Две равные колонки (решение владельца 21.10): «Как в аналогичных решениях» | «Проверка на прочность — строже». */
  pair?: LandingPair | null;
}

export interface LandingPairCol {
  label_ru: string;
  value: string;
  accent: string;
}

export interface LandingPair {
  st: LandingPairCol;
  hard: LandingPairCol;
}

export interface RecomputeRow {
  section: string;
  metric: string;
  sample: string;
  command: string;
  code_ref: string;
  artifact: string;
}

export interface Top5Metric {
  id: "confident_accuracy" | "false_confirm_all" | "exact_grade" | "within_one" | "retest_kappa_w" | string;
  value?: number | null;
  display_ru?: string | null;
  ci95?: [number, number] | null;
  k?: number | null;
  n?: number | null;
  label_ru?: string;
  condition_ru?: string;
  minutes?: number | null;
  recompute?: string;
}

export interface Top5Meta {
  bank_families?: number;
  bank_hash?: string;
  bank_commit?: string;
  generated_at?: string;
  world_ru?: string;
  how_obtained_ru?: string;
  n?: number;
}

export const NUMBERS = rawNumbers;
// Блоки появляются только при наличии JSON-артефакта (tools/publish/gen_numbers.py) — доступ без жёсткой типизации JSON.
const ANY = NUMBERS as any;

export function getTop5(): Top5Metric[] | null {
  const raw = NUMBERS as any;
  if (Array.isArray(raw.top5) && raw.top5.length > 0) return raw.top5 as Top5Metric[];
  return null;
}

export function getTop5Hard(): Top5Metric[] | null {
  const raw = NUMBERS as any;
  if (Array.isArray(raw.top5_hard) && raw.top5_hard.length > 0) return raw.top5_hard as Top5Metric[];
  return null;
}

export function getTop5Meta(): Top5Meta | null {
  const raw = NUMBERS as any;
  return (raw.top5_meta ?? null) as Top5Meta | null;
}

export function getLandingCards(): LandingCardMetric[] {
  return (NUMBERS.landing_cards ?? []) as LandingCardMetric[];
}

export function getJuryBanner(): { headline_ru: string; claims_ru: Record<string, string> } {
  return ANY.jury_banner ?? { headline_ru: "", claims_ru: {} };
}

/** Доля с ДИ из JSON-артефакта (0..1). */
export interface Frac {
  value: number;
  k?: number | null;
  n?: number | null;
  ci95?: [number, number] | null;
}

/** Симуляция продукта (А4): тот же движок, что у кандидата, на реальном банке; модельные кандидаты, не люди. */
export interface GradeVerdictView {
  n: number;
  verdict_accuracy: Frac | null;
  false_confirm: Frac | null;
  false_reject: Frac | null;
  confident_share: Frac | null;
  confident_accuracy: Frac | null;
  /** Итог после доп. этапа (FINAL №2, gen_numbers) — заголовок «Точность уверенного вердикта». */
  confident_accuracy_final?: Frac | null;
  confident_share_final?: Frac | null;
  followup_share: Frac | null;
  exact_grade: Frac | null;
  exact_grade_not_above_claim: Frac | null;
  gross_error: Frac | null;
  minutes_main?: { mean: number; p90: number } | null;
  minutes_total?: { mean: number; p90: number } | null;
  items_main?: { mean: number; min: number; max: number } | null;
  code_open_share?: { mean: number; share_sessions_ge_one_third: number } | null;
  integrity_low_share_honest?: Frac | null;
  engine_errors?: number | null;
  by_claim?: Record<string, { n: number; verdict_accuracy: Frac; false_confirm_among_overclaim: Frac; confident_share_main: Frac; exact_grade_final: Frac; minutes_total: { mean: number; p90: number } }> | null;
  world?: string;
  seeds?: number[];
  bank_families?: number;
  date?: string;
  command?: string;
  retest?: { n_pairs: number; kappa_w: number | null; exact_agreement: Frac | null; verdict_agreement: Frac | null; shared_families_mean: number | null } | null;
  noise?: number;
}

export interface GradeVerdict {
  what: string;
  main: GradeVerdictView;
  misspec: GradeVerdictView | null;
  rater_noise: GradeVerdictView | null;
  selection: any;
  claim_ru: string;
  recompute: string;
  code_ref: string;
  protocol: string;
}

export interface CheatRow {
  n: number;
  false_confirmed: Frac;
  needs_followup_main: number;
  oral_defense: number;
  preknowledge_flag: number;
  integrity_low: number;
}

export interface CheatBots {
  table: Record<string, CheatRow>;
  meta: { n_per_strategy: number; k_values: string; bot_theta: string; text_answers: string; date: string; command: string; bank_families: number };
  worst_strategy: string | null;
  claim_ru: string | null;
  recompute: string;
  code_ref: string;
}

/** Пятёрка итогового прогона (поправка №3): S-T — заголовок, жёсткие условия — рядом, всегда вместе. */
export interface Top5Item {
  id: "confident_accuracy" | "false_confirm_all" | "exact_grade" | "within_one" | "retest_kappa_w" | string;
  label_ru: string;
  value: number;
  display_ru: string;
  ci95?: [number, number] | null;
  k?: number | null;
  n?: number | null;
  condition_ru: string;
  minutes?: { mean?: number; p90?: number } | null;
  recompute?: string | null;
  with?: Record<string, Frac | { value: number; ci95?: [number, number] | null; n?: number }>;
}

/** Форма А4 (итоговый прогон {st, hard, meta}); getTop5() выше — массив для лендинга (А1). */
export function getTop5Run(): { st: Top5Item[]; hard: Top5Item[]; meta: any } {
  return { st: (ANY.top5 ?? []) as Top5Item[], hard: (ANY.top5_hard ?? []) as Top5Item[], meta: ANY.top5_meta ?? null };
}

export function getGradeVerdict(): GradeVerdict | null {
  return (ANY.grade_verdict ?? null) as GradeVerdict | null;
}

export function getCheatBots(): CheatBots | null {
  return (ANY.cheat_bots ?? null) as CheatBots | null;
}

/** Старые блоки (до 21.10) сняты как не про продукт — функции оставлены для совместимости, возвращают null. */
export function getSprtVerdict(): any {
  return ANY.sprt_verdict ?? null;
}

export function getLeakKVariants(): any {
  return ANY.leak_k_variants ?? null;
}

export function getExpertAgreement(): any {
  return ANY.expert_agreement ?? null;
}

export function getMatchingMetrics(): any {
  return ANY.matching ?? null;
}

export function getHhMatchMetrics(): any {
  return ANY.hh_match ?? null;
}

export function getAnticheatMetrics(): any {
  return ANY.anticheat ?? null;
}

export function getMutationMetrics(): any {
  return ANY.mutation_testing ?? null;
}



export function getRecomputeTable(): RecomputeRow[] {
  return (NUMBERS.recompute_table ?? []) as RecomputeRow[];
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(digits).replace(".", ",")} %`;
}

export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits).replace(".", ",");
}

/** Внешние факты о ФСП (не измерения платформы): число регионов с цитатой и источником — docs/validation/fsp_facts.json. */
export interface FspFacts {
  regions: number;
  claim_ru: string;
  source_url: string;
  source_section_ru?: string;
  checked_at: string;
}

export function getFspFacts(): FspFacts | null {
  return (ANY.fsp_facts as FspFacts | undefined) ?? null;
}

/** Подбор «один в один» на открытом генераторе другого решения (А5, проверено А15): main — заголовок, exact — опция API. */
export function getDevdev1to1(): any {
  return ANY.external_benchmarks?.devdev_1to1 ?? null;
}
