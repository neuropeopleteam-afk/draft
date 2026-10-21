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

export function getJuryBanner() {
  return NUMBERS.jury_banner;
}

export function getSprtVerdict() {
  return NUMBERS.sprt_verdict;
}

export function getLeakKVariants() {
  return NUMBERS.leak_k_variants;
}

export function getExpertAgreement() {
  return NUMBERS.expert_agreement;
}

export function getMatchingMetrics() {
  return NUMBERS.matching;
}

export function getHhMatchMetrics() {
  return NUMBERS.hh_match;
}

export function getAnticheatMetrics() {
  return NUMBERS.anticheat;
}

export function getMutationMetrics() {
  return NUMBERS.mutation_testing;
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
