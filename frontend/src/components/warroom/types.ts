export type NodeId =
  | "clients"
  | "lb"
  | "gw"
  | "core"
  | "pgb"
  | "pg"
  | "replica"
  | "redis"
  | "kafka"
  | "consumers"
  | "ext";

export type Tone = "bad" | "warn" | "ok" | "idle";

export interface MeasureParamSpec {
  key: string;
  label: string;
  type: "int";
  min: number;
  max: number;
  step: number;
  default: number;
  unit: string;
  hint: string;
}

export interface MeasureSpec {
  id: string;
  label: string;
  tech: string;
  badge: string;
  at: NodeId;
  base_cost_rub: number;
  params: MeasureParamSpec[];
}

export interface MeasureSelection {
  id: string;
  params: Record<string, number>;
}

export interface ScenarioPatch {
  label: string;
  lang: string;
  code: string;
}

export interface ScenarioCheck {
  id: string;
  label: string;
  forbid: boolean;
  passed?: boolean;
}

export interface RubricCriterionSpec {
  id: string;
  title: string;
  weight: number;
  score?: number;
  quote?: string;
}

export interface ScenarioPublic {
  id: string;
  direction: string;
  direction_title: string;
  target_grade: "senior" | "lead" | "principal";
  title: string;
  short: string;
  service: string;
  release: string;
  seed: number;
  story: string;
  labels: Partial<Record<NodeId, string>>;
  problem: NodeId[];
  base: {
    rps: number;
    p99_ms: number;
    err: number;
    loss: number;
    base_cost_rub: number;
    max_conn?: number;
    ext_sec?: number;
  };
  extra: {
    label: string;
    base: number;
    best: number;
    unit: string;
    limit: number;
  };
  slo: {
    p99_limit_ms: number;
    error_limit_pct: number;
    extra_limit: number;
    cost_budget_rub_month: number;
  };
  patches: ScenarioPatch[];
  checks: ScenarioCheck[];
  rubric: RubricCriterionSpec[];
  incident?: Record<string, unknown>;
  demo_mode?: boolean;
}

export interface SimulateMetrics {
  rps: number;
  incoming_rps: number;
  p99_ms: number;
  error_rate_pct: number;
  loss_rub_sec: number;
  extra_label: string;
  extra_value: number;
  extra_unit: string;
  mttr_s: number;
  cost_rub_month: number;
  base_cost_rub_month: number;
  measures_cost_rub_month: number;
  cost_budget_rub_month: number;
}

export interface SimulateResult {
  scenario_id: string;
  direction: string;
  target_grade: string;
  seed: number;
  metrics: SimulateMetrics;
  slo: {
    p99_limit_ms: number;
    p99_ok: boolean;
    error_limit_pct: number;
    error_ok: boolean;
    extra_limit: number;
    extra_ok: boolean;
    cost_budget_rub_month: number;
    within_budget: boolean;
    slo_met: boolean;
  };
  scores: {
    progress: number;
    sim_score: number;
    actions_score: number;
    code_score: number;
    cost_efficiency: number;
    penalty_count?: number;
  };
  code_checks: ScenarioCheck[];
  node_tones: Record<NodeId, Tone>;
  feedback: {
    missing_measures: string[];
    param_warnings: string[];
    failed_code_checks: string[];
    deploy_log: string[];
  };
}

export interface RubricResult {
  rubric_score: number;
  reviewer_mode: string;
  injection_blocked: boolean;
  injection_signals: string[];
  meta_stripped: string[];
  comment_ru: string;
  criteria: {
    id: string;
    title: string;
    weight: number;
    score: number;
    quote: string;
  }[];
}

export interface IncidentStage {
  scenario_id: string;
  direction: string;
  target_grade: string;
  status: "completed" | "in_progress" | "skipped";
  score: number;
  points_gpcm: number;
  actions_score: number;
  code_score: number;
  rubric_score: number;
  criteria: Record<string, number>;
  slo_met: boolean;
  cost_rub_month: number;
  cost_budget_rub_month: number;
  mttr_s: number;
  time_spent_s: number;
  passed: boolean;
  confirmed_grade: string;
  summary_ru: string;
}

export interface EvaluateResult extends SimulateResult {
  mode?: "combat" | "demo";
  rubric: RubricResult;
  total_score: number;
  passed: boolean;
  confirmed_grade: string;
  points_gpcm: number;
  incident_stage: IncidentStage;
  sha256_sig: string;
  summary_ru: string;
  voice_summary_ru: string;
  attempt_id?: string | null;
  saved_to_db?: boolean;
  sprt_preview?: {
    verdict_status?: "confirmed" | "needs_followup" | "not_confirmed";
    verdict_title_ru?: string;
    stage_points?: number;
    max_stage_points?: number;
    explanation_ru?: string;
    theta_before?: number;
    theta_post: number;
    se_before?: number;
    se_post: number;
    llr_delta: number;
  } | null;
}

export interface AntiCheatContourSpec {
  n: number;
  id: string;
  name: string;
  color: string;
  description: string;
}

export interface AntiCheatSignalSpec {
  n: number;
  c: number;
  code: string;
  name: string;
  pts: number;
  how_it_works: string;
}

export interface GraderInspectLayer {
  id: string;
  title: string;
  triggered: boolean;
  details: string[];
}

export interface AntiCheatInspectResult {
  demo_mode?: boolean;
  demo_notice_ru?: string;
  total_signals_catalog: number;
  triggered_count: number;
  triggered_numbers: number[];
  risk_points: number;
  integrity_level: "high" | "medium" | "low";
  integrity_title: string;
  defense_recommended: boolean;
  defense_why: string | null;
  grader_inspect: {
    verdict: string;
    route: string;
    normalized: string;
    normalizations: string[];
    signals: string[];
    signal_titles: string[];
    meta_removed: string[];
    cleaned_text: string;
    soft_signals: string[];
    layers: GraderInspectLayer[];
  };
  marker_detected: boolean;
  marker_word: string | null;
  copy_decoy?: {
    decoy_stem: string;
    decoy_expected: string;
    triggered: boolean;
    matched_markers: string[];
  };
  integrity_followup?: {
    honesty_index: number;
    risk_points: number;
    decoy_hits: number;
    needs_followup_stage: boolean;
    action: string;
    action_title_ru: string;
    triggered_factors: string[];
    employer_reason_ru: string;
  };
  keystroke_cv: number;
  person_fit_lz: number | null;
  lz_items: { a: number; b: number; x: number; t: number }[];
  events_log: { signals: number[]; text: string; severe?: boolean }[];
  passport: Record<string, unknown> | null;
}
