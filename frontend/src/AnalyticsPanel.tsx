import { useLanguage } from "./i18n";
import { useEffect, useMemo, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import {
  api,
  ENGINES,
  NAMES,
  type Analysis,
  type EngineId,
  type Job,
} from "./types";
import {
  comparisonLabel,
  type AnalyticsReport,
  type ComparisonRow,
} from "./analytics-types";
import AnalyticsChart from "./AnalyticsChart";

type Props = {
  analysis: Analysis;
  jobs: Job[];
  focused: string | null;
  onSelect: (key: string) => void;
  onThreshold: (engine: EngineId, value: number) => void;
};
const reasons: Record<string, string> = {
  not_calculated: "미계산",
  previous_configuration: "이전 실행 설정",
  failed: "실패",
  cancelled: "취소",
  incomplete: "미완료",
  invalid_result: "결과 확인 필요",
};
const chartBase = {
  textStyle: {
    fontFamily: "Inter, sans-serif",
    color: "#526171",
    fontSize: 11,
  },
  grid: { left: 64, right: 30, top: 36, bottom: 62 },
  tooltip: { trigger: "item", renderMode: "richText", confine: true },
};

export default function AnalyticsPanel({
  analysis,
  jobs,
  focused,
  onSelect,
  onThreshold,
}: Props) {
  const { language, t, message } = useLanguage();
  const [selected, setSelected] = useState<EngineId[] | null>(null);
  const format = useMemo(
    () =>
      (value: number | null, digits = 2) =>
        value === null
          ? "—"
          : value.toLocaleString(language, { maximumFractionDigits: digits }),
    [language],
  );
  const [topK, setTopK] = useState(10);
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [pairKey, setPairKey] = useState("");
  const [order, setOrder] = useState("mean");
  const [conflictsOnly, setConflictsOnly] = useState(false);
  const [minimumSpread, setMinimumSpread] = useState(0);
  const [sensitivityEngine, setSensitivityEngine] = useState<EngineId>("foldx");
  const [previews, setPreviews] = useState<Partial<Record<EngineId, string>>>(
    {},
  );
  const revision = jobs.map((job) => `${job.id}:${job.status}`).join("|");
  const thresholdRevision = JSON.stringify(analysis.thresholds);
  const query = useMemo(() => {
    const params = new URLSearchParams({ top_k: String(topK) });
    if (selected) {
      if (!selected.length) params.append("engines", "");
      selected.forEach((engine) => params.append("engines", engine));
    }
    return params.toString();
  }, [selected, topK]);
  const path = `/analyses/${analysis.id}/analytics?${query}`;
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api<AnalyticsReport>(path)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((reason) => {
        if (!cancelled)
          setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, revision, thresholdRevision, retry]);

  const engines = selected ?? report?.engines ?? [];
  const rankColumns =
    report?.available.filter(
      (engine) =>
        engine.complete_count === 0 || report.engines.includes(engine.id),
    ) ?? [];
  const pair =
    report?.pairs.find((item) => `${item.left}|${item.right}` === pairKey) ??
    report?.pairs[0];
  const currentEngine = report?.engines.includes(sensitivityEngine)
    ? sensitivityEngine
    : report?.engines[0];
  const sensitivity = currentEngine
    ? report?.sensitivity[currentEngine]
    : undefined;
  const previewText = currentEngine
    ? (previews[currentEngine] ??
      (sensitivity?.saved_applicable
        ? String(sensitivity.saved_threshold?.value)
        : ""))
    : "";
  const preview =
    previewText.trim() &&
    Number.isFinite(Number(previewText)) &&
    Number(previewText) > 0
      ? Number(previewText)
      : null;
  const members =
    report?.rows.filter(
      (row) =>
        currentEngine &&
        preview !== null &&
        row.scores[currentEngine]!.value >= preview,
    ) ?? [];
  const displayRows = [...(report?.rows ?? [])]
    .filter(
      (row) =>
        (!conflictsOnly || row.sign_conflict) &&
        row.rank_spread >= minimumSpread,
    )
    .sort((a, b) => {
      if (order === "spread" && b.rank_spread !== a.rank_spread)
        return b.rank_spread - a.rank_spread;
      return (
        (a.mean_rank ?? 0) - (b.mean_rank ?? 0) ||
        a.chain.localeCompare(b.chain) ||
        a.number - b.number ||
        a.icode.localeCompare(b.icode)
      );
    });
  const focusedRow = report?.rows.find((row) => row.key === focused);

  const scatterOption = useMemo(() => {
    if (!pair || !report) return {};
    return {
      ...chartBase,
      xAxis: {
        type: "value",
        name: `${NAMES[pair.left]} (${report.sensitivity[pair.left]!.unit})`,
        nameLocation: "middle",
        nameGap: 38,
        scale: true,
      },
      yAxis: {
        type: "value",
        name: `${NAMES[pair.right]} (${report.sensitivity[pair.right]!.unit})`,
        nameGap: 18,
        scale: true,
      },
      series: [
        {
          type: "scatter",
          symbolSize: 10,
          data: report.rows.map((row) => ({
            name: comparisonLabel(row),
            key: row.key,
            value: [
              row.scores[pair.left]!.value,
              row.scores[pair.right]!.value,
            ],
            itemStyle: {
              color:
                row.key === focused
                  ? "#c28a34"
                  : row.scores[pair.left]!.value *
                        row.scores[pair.right]!.value <
                      0
                    ? "#a65555"
                    : "#3f729d",
              opacity: 0.85,
            },
          })),
        },
      ],
    };
  }, [report, pair, focused]);
  const matrixOption = useMemo(() => {
    if (!report) return {};
    const data = report.engines.flatMap((left, x) =>
      report.engines.map((right, y) => {
        const match = report.pairs.find(
          (item) =>
            (item.left === left && item.right === right) ||
            (item.left === right && item.right === left),
        );
        const values = new Set(
          report.rows.map((row) => row.scores[left]!.value),
        );
        const rho =
          left === right
            ? report.common_count > 1 && values.size > 1
              ? 1
              : null
            : match?.spearman;
        return {
          name: `${NAMES[left]} / ${NAMES[right]}`,
          pair: [left, right],
          value: [x, y, rho],
          label: { show: true, formatter: rho == null ? "—" : rho.toFixed(2) },
          itemStyle: { color: rho == null ? "#eef1f4" : undefined },
        };
      }),
    );
    return {
      ...chartBase,
      grid: { left: 85, right: 20, top: 30, bottom: 90 },
      xAxis: {
        type: "category",
        data: report.engines.map((e) => NAMES[e]),
        axisLabel: { interval: 0 },
      },
      yAxis: { type: "category", data: report.engines.map((e) => NAMES[e]) },
      visualMap: {
        min: -1,
        max: 1,
        orient: "horizontal",
        left: "center",
        bottom: 6,
        inRange: { color: ["#bc7772", "#f3f5f7", "#467ca8"] },
      },
      series: [{ type: "heatmap", data }],
    };
  }, [report]);
  const sensitivityOption = useMemo(() => {
    if (!sensitivity || !currentEngine) return {};
    const maximum =
      sensitivity.points[sensitivity.points.length - 1]?.threshold ?? 0;
    const max = Math.max(maximum * 1.05, preview ?? 0, 1);
    const curves = [
      {
        type: "line",
        step: "end",
        symbolSize: 7,
        lineStyle: { color: "#467ca8", width: 2 },
        itemStyle: { color: "#467ca8" },
        data: sensitivity.points.map((point) => ({
          name:
            point.threshold === 0
              ? t("양수 임계값 → 0")
              : t(
                  "임계값 {0} {1}",
                  format(point.threshold, 6),
                  sensitivity.unit,
                ),
          threshold: point.threshold,
          value: [point.threshold, point.count],
        })),
      },
    ];
    const markers =
      preview === null
        ? []
        : [
            {
              type: "scatter",
              symbolSize: 13,
              itemStyle: { color: "#b27e27" },
              data: [
                {
                  name: t("미리보기 · {0}개", members.length),
                  threshold: preview,
                  value: [preview, members.length],
                },
              ],
            },
          ];
    const saved = sensitivity.saved_applicable
      ? [
          {
            type: "scatter",
            symbol: "diamond",
            symbolSize: 12,
            itemStyle: { color: "#34714f" },
            data: [
              {
                name: t("저장된 기준"),
                threshold: sensitivity.saved_threshold!.value!,
                value: [
                  sensitivity.saved_threshold!.value,
                  sensitivity.saved_count,
                ],
              },
            ],
          },
        ]
      : [];
    return {
      ...chartBase,
      xAxis: {
        type: "value",
        min: 0,
        max: Math.max(
          max,
          sensitivity.saved_applicable
            ? sensitivity.saved_threshold!.value!
            : 0,
        ),
        name: t("양수 임계값 ({0})", sensitivity.unit),
        nameLocation: "middle",
        nameGap: 38,
      },
      yAxis: {
        type: "value",
        min: 0,
        minInterval: 1,
        name: t("기준 충족 잔기 수"),
        max: Math.max(1, report?.common_count ?? 1),
      },
      series: [...curves, ...saved, ...markers],
    };
  }, [
    t,
    format,
    sensitivity,
    currentEngine,
    preview,
    members.length,
    report?.common_count,
  ]);

  function selectResidue(row: ComparisonRow) {
    onSelect(row.key);
  }
  return (
    <section
      className="panel analytics-panel"
      aria-labelledby="analytics-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="analytics-title">{t("결과 해석")}</h2>
          {report?.provisional && (
            <span className="status-dot running">
              {t("계산 진행 중 · 잠정 집계")}
            </span>
          )}
        </div>
        {report && !loading && !error && report.common_count > 0 && (
          <a
            className="button secondary small"
            href={`/api/analyses/${analysis.id}/analytics.csv?${query}`}
          >
            <Download size={14} /> {t("비교 결과 CSV")}
          </a>
        )}
      </div>
      <div className="analytics-controls">
        <fieldset>
          <legend>{t("비교 엔진")}</legend>
          {ENGINES.map((engine) => (
            <label key={engine}>
              <input
                type="checkbox"
                checked={engines.includes(engine)}
                disabled={
                  !report ||
                  (!report.available.find((item) => item.id === engine)
                    ?.complete_count &&
                    !engines.includes(engine))
                }
                onChange={() =>
                  setSelected(
                    engines.includes(engine)
                      ? engines.filter((item) => item !== engine)
                      : [...engines, engine],
                  )
                }
              />
              {NAMES[engine]}{" "}
              <small>
                {report?.available.find((item) => item.id === engine)
                  ?.complete_count ?? 0}
                {t("개 완료")}
              </small>
            </label>
          ))}
        </fieldset>
        <label>
          {t("상위 후보 K")}{" "}
          <input
            aria-label={t("상위 후보 수")}
            type="number"
            min="1"
            max={Math.max(1, report?.common_count ?? 1)}
            value={Math.min(topK, Math.max(1, report?.common_count ?? topK))}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isInteger(value) && value > 0) setTopK(value);
            }}
          />
        </label>
      </div>
      {loading && (
        <p className="analytics-message" role="status">
          {t("결과 해석을 갱신하고 있습니다…")}
        </p>
      )}
      {error && (
        <div className="analytics-message warning-text" role="alert">
          {message(error)}{" "}
          <button
            className="button secondary small"
            onClick={() => setRetry((value) => value + 1)}
          >
            <RefreshCw size={13} /> {t("다시 불러오기")}
          </button>
        </div>
      )}
      {report && !loading && !error && (
        <>
          <div className="analytics-summary">
            <p>
              {t("전체 분석 잔기")} <strong>{report.total_count}</strong>
              {t("개 · 공통 완료")} <strong>{report.common_count}</strong>
              {t("개 · 제외")} <strong>{report.excluded_count}</strong>
              {t("개")}
            </p>
            <p>
              {t(
                "비교 대상은 선택한 모든 엔진에서 반복 계산을 완료한 공통 잔기입니다. 도구별 순위를 동일 비중으로 반영합니다.",
              )}
            </p>
            <details>
              <summary>{t("분석 대상 및 제외 사유")}</summary>
              <p>
                {t(
                  "현재 분석의 전체 잔기와 엔진별 최신 실행 설정을 사용합니다. 아래 개수는 엔진마다 집계됩니다.",
                )}
              </p>
              {report.engines.map((engine) => (
                <p key={engine}>
                  <strong>{NAMES[engine]}</strong> ·{" "}
                  {Object.entries(report.exclusions[engine] ?? {})
                    .map(
                      ([reason, count]) =>
                        `${t(reasons[reason] ?? reason)} ${count}`,
                    )
                    .join(" · ") || t("제외 없음")}
                </p>
              ))}
            </details>
            {report.ranking_reason && (
              <p className="warning-text">{message(report.ranking_reason)}</p>
            )}
            {focusedRow && (
              <p>
                {t("선택 잔기")} <strong>{comparisonLabel(focusedRow)}</strong>{" "}
                <button
                  className="text-button"
                  onClick={() =>
                    document
                      .getElementById("structure-panel")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                >
                  {t("3D 구조에서 보기")}
                </button>
              </p>
            )}
          </div>
          {pair && (
            <div className="analytics-grid">
              <section className="analytics-block">
                <div className="analytics-heading">
                  <h3>{t("도구 간 점수 비교")}</h3>
                  <label>
                    {t("엔진 쌍")}{" "}
                    <select
                      aria-label={t("비교할 엔진 쌍")}
                      value={`${pair.left}|${pair.right}`}
                      onChange={(event) => setPairKey(event.target.value)}
                    >
                      {report.pairs.map((item) => (
                        <option
                          key={`${item.left}|${item.right}`}
                          value={`${item.left}|${item.right}`}
                        >
                          {NAMES[item.left]} / {NAMES[item.right]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <p>
                  Spearman ρ <strong>{format(pair.spearman, 3)}</strong> · n ={" "}
                  {pair.n}
                  {pair.reason && ` · ${message(pair.reason)}`}
                </p>
                <AnalyticsChart
                  label={t("두 계산 도구의 원점수 산점도")}
                  option={scatterOption}
                  onPick={(datum) => {
                    if (datum.key) onSelect(datum.key);
                  }}
                />
                <p className="muted">
                  {t(
                    "점을 선택하면 잔기 상세·서열·3D 구조에 반영됩니다. 붉은 점은 부호가 다른 예측입니다.",
                  )}
                </p>
              </section>
              <section className="analytics-block">
                <h3>{t("상위 후보 겹침")}</h3>
                <p>
                  Top {report.top_k}{" "}
                  {t("· 경계 점수의 동점 잔기를 포함합니다.")}
                </p>
                <div className="overlap-stat">
                  <strong>
                    {pair.jaccard === null
                      ? "—"
                      : `${format(pair.jaccard * 100, 1)}%`}
                  </strong>
                  <span>{t("Jaccard · 교집합 / 합집합")}</span>
                </div>
                <p>
                  {NAMES[pair.left]} {pair.left_top_count}
                  {t("개 ·")} {NAMES[pair.right]} {pair.right_top_count}
                  {t("개 · 공통")} {pair.common_top_keys.length}
                  {t("개")}
                </p>
                <div className="residue-links">
                  {report.rows
                    .filter((row) => pair.common_top_keys.includes(row.key))
                    .map((row) => (
                      <button
                        key={row.key}
                        className={row.key === focused ? "selected" : ""}
                        onClick={() => selectResidue(row)}
                      >
                        {comparisonLabel(row)}
                      </button>
                    ))}
                </div>
                {!pair.common_top_keys.length && (
                  <p className="muted">{t("공통 상위 후보가 없습니다.")}</p>
                )}
              </section>
              {report.engines.length >= 3 && (
                <section className="analytics-block">
                  <h3>{t("엔진별 순위상관 행렬")}</h3>
                  <p>
                    {t("모든 셀은 같은 공통 잔기")} {report.common_count}
                    {t("개를 사용합니다.")}
                  </p>
                  <AnalyticsChart
                    label={t("엔진별 Spearman 순위상관 행렬")}
                    option={matrixOption}
                    onPick={(datum) => {
                      if (datum.pair && datum.pair[0] !== datum.pair[1]) {
                        const item = report.pairs.find(
                          (p) =>
                            datum.pair!.includes(p.left) &&
                            datum.pair!.includes(p.right),
                        );
                        if (item) setPairKey(`${item.left}|${item.right}`);
                      }
                    }}
                  />
                </section>
              )}
            </div>
          )}
          {report.rows.length > 0 && (
            <>
              <div className="analytics-table-controls">
                <h3>{t("잔기 우선순위")}</h3>
                <label>
                  {t("정렬")}{" "}
                  <select
                    aria-label={t("분석 순위 정렬")}
                    value={order}
                    onChange={(event) => setOrder(event.target.value)}
                  >
                    <option value="mean">{t("평균 순위순")}</option>
                    <option value="spread">{t("순위 차이가 큰 순서")}</option>
                  </select>
                </label>
                <label>
                  {t("최소 순위 차이")}{" "}
                  <input
                    aria-label={t("최소 순위 차이")}
                    className="rank-spread-input"
                    type="number"
                    min="0"
                    step="0.5"
                    value={minimumSpread}
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (Number.isFinite(value) && value >= 0)
                        setMinimumSpread(value);
                    }}
                  />
                </label>
                <label className="checkline">
                  <input
                    type="checkbox"
                    checked={conflictsOnly}
                    onChange={(event) => setConflictsOnly(event.target.checked)}
                  />
                  {t("부호 불일치 잔기")}
                </label>
              </div>
              <div className="table-wrap">
                <table aria-label={t("도구별 순위와 평균 순위")}>
                  <thead>
                    <tr>
                      <th>{t("잔기")}</th>
                      <th>{t("평균 순위")}</th>
                      {rankColumns.map((engine) => (
                        <th key={engine.id}>
                          {engine.name}
                          <small>
                            {engine.unit} {t("· 순위")}
                          </small>
                        </th>
                      ))}
                      <th>{t("순위 차이")}</th>
                      <th>{t("예측 방향")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((row) => (
                      <tr
                        key={row.key}
                        className={row.key === focused ? "row-focused" : ""}
                      >
                        <td>
                          <button
                            className="text-button"
                            onClick={() => selectResidue(row)}
                          >
                            {comparisonLabel(row)}
                          </button>
                        </td>
                        <td className="mono">{format(row.mean_rank)}</td>
                        {rankColumns.map(({ id: engine }) => {
                          const score = row.scores[engine];
                          if (!score)
                            return (
                              <td key={engine} aria-label={t("완료 결과 없음")}>
                                —
                              </td>
                            );
                          return (
                            <td key={engine}>
                              <span
                                className={
                                  score.value >= 0 ? "positive" : "negative"
                                }
                              >
                                {format(score.value, 4)}
                              </span>
                              <small>
                                {t("순위")} {format(score.rank)}
                                {score.top_member ? t(" · 상위 후보") : ""}
                              </small>
                              <small>
                                n={score.completed} · SD {format(score.sd, 4)}
                              </small>
                            </td>
                          );
                        })}
                        <td>{format(row.rank_spread)}</td>
                        <td>
                          {row.sign_conflict
                            ? t("부호 불일치")
                            : t("부호 불일치 없음")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!displayRows.length && (
                  <p className="analytics-message">
                    {t("조건에 해당하는 잔기가 없습니다.")}
                  </p>
                )}
              </div>
              <p className="analytics-footnote">
                {t(
                  "점수 내림차순 · 동점은 평균 순위 · 평균 순위가 낮을수록 우선 · SD는 반복 계산 변동성",
                )}
              </p>
            </>
          )}
          {currentEngine && sensitivity && report.rows.length > 0 && (
            <section className="analytics-sensitivity">
              <div className="analytics-heading">
                <h3>{t("임계값 민감도")}</h3>
                <label>
                  {t("엔진")}{" "}
                  <select
                    aria-label={t("민감도 분석 엔진")}
                    value={currentEngine}
                    onChange={(event) =>
                      setSensitivityEngine(event.target.value as EngineId)
                    }
                  >
                    {report.engines.map((engine) => (
                      <option value={engine} key={engine}>
                        {NAMES[engine]}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="analytics-grid">
                <div>
                  <AnalyticsChart
                    label={t("양수 임계값에 따른 후보 잔기 수")}
                    option={sensitivityOption}
                    onPick={(datum) => {
                      if (datum.threshold !== undefined && datum.threshold > 0)
                        setPreviews((previous) => ({
                          ...previous,
                          [currentEngine]: String(datum.threshold),
                        }));
                    }}
                  />
                  <p className="muted">
                    {t(
                      "점수 ≥ 임계값 · 왼쪽 끝 0은 양수 임계값이 0에 가까워지는 경우입니다.",
                    )}
                  </p>
                </div>
                <div className="sensitivity-preview">
                  <label>
                    {t("미리보기 임계값 ·")} {sensitivity.unit}
                    <input
                      aria-label={t("미리보기 임계값")}
                      type="number"
                      step="any"
                      min="0"
                      placeholder={t("양수 입력 또는 그래프 점 선택")}
                      value={previewText}
                      onChange={(event) =>
                        setPreviews((previous) => ({
                          ...previous,
                          [currentEngine]: event.target.value,
                        }))
                      }
                    />
                  </label>
                  {previewText && preview === null && (
                    <p className="warning-text">
                      {t("유한한 양수 임계값을 입력하세요.")}
                    </p>
                  )}
                  <p>
                    {sensitivity.saved_applicable
                      ? t(
                          "저장된 기준 {0} {1} · {2}개",
                          sensitivity.saved_threshold!.value,
                          sensitivity.unit,
                          sensitivity.saved_count,
                        )
                      : sensitivity.saved_threshold?.value != null
                        ? t("저장된 기준은 이전 실행 설정에 해당합니다.")
                        : t("저장된 기준이 없습니다.")}
                  </p>
                  {preview !== null && (
                    <>
                      <p className="preview-count">
                        <strong>{members.length}</strong> /{" "}
                        {report.common_count}
                        {t("개 충족")}
                      </p>
                      <div className="residue-links">
                        {members.map((row) => (
                          <button
                            key={row.key}
                            className={row.key === focused ? "selected" : ""}
                            onClick={() => selectResidue(row)}
                          >
                            {comparisonLabel(row)}
                          </button>
                        ))}
                      </div>
                      <button
                        className="button secondary"
                        onClick={() => onThreshold(currentEngine, preview)}
                      >
                        {t("근거 입력 후 기준 저장")}
                      </button>
                    </>
                  )}
                  <p className="muted">
                    {t(
                      "미리보기 값을 선택한 뒤 기존 판정 기준 양식에서 검증 근거와 함께 저장할 수 있습니다.",
                    )}
                  </p>
                </div>
              </div>
            </section>
          )}
        </>
      )}
    </section>
  );
}
