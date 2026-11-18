export const ENGINES = [
  "foldx",
  "evoef",
  "budealascan",
  "flex_ddg",
  "saambe3d",
] as const;
export type EngineId = (typeof ENGINES)[number];
export const NAMES: Record<string, string> = {
  foldx: "FoldX",
  evoef: "EvoEF",
  saambe3d: "SAAMBE-3D",
  budealascan: "BudeAlaScan",
  flex_ddg: "Flex ddG",
};
export type Residue = {
  key: string;
  chain: string;
  number: number;
  icode: string;
  wt: string;
  name: string;
  engine_chain: string;
  engine_number: number;
  warnings: string[];
  distance: number | null;
  interface: boolean;
  eligible: boolean;
  selected: boolean;
};
export type Analysis = {
  id: string;
  name: string;
  created: number;
  rows: Residue[];
  mapping: Residue[];
  warnings: string[];
  blocking_hetero: unknown[];
  groups: string[][];
  input: {
    group1: string[];
    group2: string[];
    scan_chains: string[];
    cutoff: number;
    model: number;
  };
  thresholds: Record<
    string,
    { value: number | null; unit: string; evidence: string }
  >;
};
export type Score = {
  value: number | null;
  sd: number | null;
  unit: string | null;
  completed: number;
  planned: number;
  statuses: string[];
  support: boolean | null;
  details: unknown[];
  jobs: string[];
};
export type ResultRow = Residue & {
  scores: Record<string, Score>;
  support_count: number;
  eligible_count: number;
  selected_count: number;
  consensus: boolean;
  provisional: boolean;
};
export type Job = {
  id: string;
  analysis_id: string;
  engine: string;
  status: string;
  cancel: number;
  created: number;
  error: string | null;
  result: unknown;
  payload: {
    repeat: number;
    planned_repeats: number;
    validation?: boolean;
    install?: boolean;
    residues: Residue[];
  };
};
export type Engine = {
  id: EngineId;
  name: string;
  executable: string;
  data_dir: string;
  version: string;
  image: string;
  status: string;
  platform: string;
  validation?: { job_id: string; note?: string };
  error?: string;
};
export type StructureInfo = {
  id: string;
  name: string;
  models: {
    index: number;
    serial: number;
    chains: { id: string; count: number }[];
    hetero: unknown[];
  }[];
  warnings: string[];
};
export const residueLabel = (r: Residue) =>
  `${r.chain.trim() || "∅"}:${r.wt}${r.number}${r.icode}`;
export const STATUS: Record<string, string> = {
  ready: "실행 가능",
  not_installed: "설정 필요",
  needs_validation: "검증 필요",
  failed: "실패",
  unsupported: "미지원",
  queued: "대기",
  running: "계산 중",
  succeeded: "완료",
  cancelled: "취소",
};
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    headers:
      method === "GET"
        ? {}
        : {
            "Content-Type": "application/json",
            "X-Hotspot-Client": "local-ui",
          },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json();
}
