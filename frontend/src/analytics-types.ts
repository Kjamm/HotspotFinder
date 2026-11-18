import type { EngineId } from "./types";

export type ComparisonScore = {
  value: number;
  unit: string;
  sd: number | null;
  completed: number;
  planned: number;
  fingerprint: string;
  rank: number;
  top_member: boolean;
};
export type ComparisonRow = {
  key: string;
  chain: string;
  number: number;
  icode: string;
  wt: string;
  scores: Partial<Record<EngineId, ComparisonScore>>;
  mean_rank: number | null;
  rank_spread: number;
  sign_conflict: boolean;
};
export type ComparisonPair = {
  left: EngineId;
  right: EngineId;
  n: number;
  spearman: number | null;
  reason: string | null;
  jaccard: number | null;
  left_top_count: number;
  right_top_count: number;
  common_top_keys: string[];
};
export type Sensitivity = {
  unit: string;
  points: { threshold: number; count: number }[];
  saved_threshold: {
    value: number | null;
    unit: string;
    fingerprint?: string;
    evidence: string;
  } | null;
  saved_applicable: boolean;
  saved_count: number | null;
};
export type AnalyticsReport = {
  analysis_id: string;
  engines: EngineId[];
  available: {
    id: EngineId;
    name: string;
    unit: string;
    has_results: boolean;
    complete_count: number;
    fingerprint: string | null;
  }[];
  total_count: number;
  common_count: number;
  excluded_count: number;
  exclusions: Partial<Record<EngineId, Record<string, number>>>;
  top_k: number;
  requested_top_k: number;
  provisional: boolean;
  ranking_reason: string | null;
  rows: ComparisonRow[];
  pairs: ComparisonPair[];
  sensitivity: Partial<Record<EngineId, Sensitivity>>;
};
export const comparisonLabel = (row: ComparisonRow) =>
  `${row.chain.trim() || "∅"}:${row.wt}${row.number}${row.icode}`;
