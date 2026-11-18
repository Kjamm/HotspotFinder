import { LanguageProvider, useLanguage } from "./i18n";
import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRight,
  Check,
  ChevronRight,
  Database,
  Download,
  FileUp,
  FlaskConical,
  Layers3,
  LoaderCircle,
  Microscope,
  Play,
  Plus,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Square,
  Workflow,
  X,
} from "lucide-react";
import {
  api,
  Analysis,
  Engine,
  ENGINES,
  Job,
  NAMES,
  Residue,
  ResultRow,
  residueLabel,
  Score,
  STATUS,
  StructureInfo,
} from "./types";
import "./style.css";
import EngineCard from "./EngineCard";
const StructureViewer = lazy(() => import("./StructureViewer"));
const AnalyticsPanel = lazy(() => import("./AnalyticsPanel"));
const units: Record<string, string> = {
  foldx: "kcal/mol",
  evoef: "EvoEF score",
  saambe3d: "kcal/mol",
  budealascan: "kcal/mol",
  flex_ddg: "REU",
};

function App() {
  const { language, setLanguage, t, message } = useLanguage();
  const [page, setPage] = useState<"workbench" | "engines" | "jobs">(
    "workbench",
  );
  const [history, setHistory] = useState<
      { id: string; name: string; candidates: number }[]
    >([]),
    [engines, setEngines] = useState<Engine[]>([]);
  const [source, setSource] = useState<StructureInfo | null>(null),
    [model, setModel] = useState(0),
    [g1, setG1] = useState<string[]>([]),
    [g2, setG2] = useState<string[]>([]),
    [scan, setScan] = useState<string[]>([]),
    [cutoff, setCutoff] = useState(5),
    [gly, setGly] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null),
    [rows, setRows] = useState<ResultRow[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [allJobs, setAllJobs] = useState<Job[]>([]);
  const [selection, setSelection] = useState<Set<string>>(new Set()),
    [focused, setFocused] = useState<string | null>(null),
    [engineSelection, setEngineSelection] = useState<string[]>([]);
  const [search, setSearch] = useState(""),
    [filter, setFilter] = useState("interface"),
    [sort, setSort] = useState("position"),
    [view, setView] = useState<"table" | "heatmap">("heatmap");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [log, setLog] = useState<string | null>(null),
    [repeats, setRepeats] = useState(1),
    [flexRepeats, setFlexRepeats] = useState(35),
    [concurrency, setConcurrency] = useState(1),
    [timeout, setTimeoutValue] = useState(7200);
  const [thresholdEngine, setThresholdEngine] = useState("foldx"),
    [threshold, setThreshold] = useState(""),
    [evidence, setEvidence] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const refresh = async () => {
    const [h, e, j, r] = await Promise.all([
      api<typeof history>("/analyses"),
      api<Engine[]>("/engines"),
      api<Job[]>("/jobs"),
      api<{ concurrency: number }>("/runtime"),
    ]);
    setHistory(h);
    setEngines(e);
    setAllJobs(j);
    setConcurrency(r.concurrency);
  };
  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    let gone = false;
    let pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const [e, j, res] = await Promise.all([
          api<Engine[]>("/engines"),
          api<Job[]>("/jobs"),
          analysis
            ? api<{ rows: ResultRow[]; jobs: Job[] }>(
                `/analyses/${analysis.id}/results`,
              )
            : Promise.resolve(null),
        ]);
        if (!gone) {
          setEngines(e);
          setAllJobs(j);
          if (res) {
            setRows(res.rows);
            setJobs(res.jobs);
          }
        }
      } catch (e) {
        if (!gone) setError(String(e));
      } finally {
        pending = false;
      }
    };
    const timer = window.setInterval(poll, 2500);
    return () => {
      gone = true;
      window.clearInterval(timer);
    };
  }, [analysis?.id]);
  const setupSource = (s: StructureInfo) => {
    setSource(s);
    const m = s.models[0];
    setModel(m.index);
    setG1(m.chains.slice(0, 1).map((c) => c.id));
    setG2(m.chains.slice(1, 2).map((c) => c.id));
    setScan(m.chains.slice(0, 1).map((c) => c.id));
  };
  const openAnalysis = async (id: string) => {
    const [a, res] = await Promise.all([
      api<Analysis>(`/analyses/${id}`),
      api<{ rows: ResultRow[]; jobs: Job[] }>(`/analyses/${id}/results`),
    ]);
    setAnalysis(a);
    setEngineSelection(
      engines
        .filter(
          (e) => e.status === "ready" && ["foldx", "evoef"].includes(e.id),
        )
        .map((e) => e.id),
    );
    setRows(res.rows);
    setJobs(res.jobs);
    setSelection(new Set(a.rows.filter((r) => r.selected).map((r) => r.key)));
    setFocused(null);
    setSource(null);
    setPage("workbench");
    setSearch("");
    setFilter("interface");
  };
  const create = () =>
    act(async () => {
      if (!source) return;
      const a = await api<Analysis>("/analyses", "POST", {
        structure_id: source.id,
        model,
        group1: g1,
        group2: g2,
        scan_chains: scan,
        cutoff,
        include_gly: gly,
      });
      await openAnalysis(a.id);
      await refresh();
    });
  const start = (flex = false) =>
    act(async () => {
      if (!analysis) return;
      const requested = flex ? ["flex_ddg"] : engineSelection;
      if (!requested.length) throw Error("실행할 엔진을 선택하세요.");
      await api(`/analyses/${analysis.id}/run`, "POST", {
        engines: requested,
        residues: [...selection],
        repeats: flex ? flexRepeats : singleScan ? 1 : repeats,
        timeout,
      });
      const res = await api<{ rows: ResultRow[]; jobs: Job[] }>(
        `/analyses/${analysis.id}/results`,
      );
      setRows(res.rows);
      setJobs(res.jobs);
      setNotice(
        `${selection.size}개 잔기의 ${requested.map((e) => NAMES[e]).join(", ")} 작업을 등록했습니다.`,
      );
      await refresh();
    });
  const toggle = (key: string) =>
    setSelection((s) => {
      const next = new Set(s);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  const toggleChain = (
    c: string,
    values: string[],
    set: (v: string[]) => void,
  ) => set(values.includes(c) ? values.filter((x) => x !== c) : [...values, c]);
  const visible = rows
    .filter(
      (r) =>
        (filter !== "interface" || r.interface) &&
        (filter !== "consensus" || r.consensus) &&
        (filter !== "selected" || selection.has(r.key)) &&
        residueLabel(r).toLowerCase().includes(search.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "distance"
        ? (a.distance ?? Infinity) - (b.distance ?? Infinity)
        : sort === "support"
          ? b.support_count - a.support_count
          : a.chain.localeCompare(b.chain) ||
            a.number - b.number ||
            a.icode.localeCompare(b.icode),
    );
  const twoChainPartners = analysis?.groups.every(
    (group) => group.length === 1,
  );
  const singleScan = engineSelection.includes("saambe3d");
  const focusedRow = rows.find((r) => r.key === focused) || null;
  const running = allJobs.filter((j) =>
    ["queued", "running"].includes(j.status),
  );
  const scoreCell = (s: Score | undefined) =>
    !s ? (
      <span className="empty-value">—</span>
    ) : s.value === null ? (
      <span
        className={
          "job-status " + (s.statuses.includes("running") ? "running" : "")
        }
      >
        {s.statuses.includes("running")
          ? t("계산 중")
          : s.statuses.map((st) => t(STATUS[st] ?? st)).join(" / ")}
      </span>
    ) : (
      <span className={s.value >= 0 ? "positive" : "negative"}>
        {s.value > 0 ? "+" : ""}
        {s.value.toFixed(2)}
        <small>
          {s.completed}/{s.planned}
          {s.sd !== null ? ` · SD ${s.sd.toFixed(2)}` : ""}
        </small>
      </span>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Workflow size={23} />
          </div>
          <div>HotspotFinder</div>
        </div>
        <nav>
          {[
            ["workbench", Microscope, t("계면 분석")],
            ["jobs", Activity, t("계산 작업")],
            ["engines", Settings2, t("계산 엔진")],
          ].map(([id, Icon, label]) => {
            const I = Icon as typeof Microscope;
            return (
              <button
                key={String(id)}
                className={page === id ? "active" : ""}
                onClick={() => setPage(id as typeof page)}
              >
                <I size={18} />
                {String(label)}
                {id === "jobs" && running.length > 0 && <b>{running.length}</b>}
              </button>
            );
          })}
        </nav>
        <div className="history-head">
          {t("최근 분석")}{" "}
          <button
            aria-label={t("새 분석")}
            onClick={() => {
              setSource(null);
              setAnalysis(null);
              setRows([]);
              setJobs([]);
              setPage("workbench");
            }}
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="history-list">
          {history.length ? (
            history.map((h) => (
              <button
                key={h.id}
                className={analysis?.id === h.id ? "selected" : ""}
                onClick={() => act(() => openAnalysis(h.id))}
              >
                <Layers3 size={15} />
                <span>
                  {h.name}
                  <small>
                    {h.candidates}
                    {t("개 계산 후보")}
                  </small>
                </span>
              </button>
            ))
          ) : (
            <p>
              {t("첫 분석을 시작하면")} <br />
              {t("이곳에 기록됩니다.")}
            </p>
          )}
        </div>
        <div className="sidebar-footer">
          <ShieldCheck size={17} />
          <div>
            {t("로컬 계산")}
            <span>{t("PDB는 이 컴퓨터에 보관됩니다.")}</span>
          </div>
          <i />
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            {t("분석 공간")} <ChevronRight size={14} />{" "}
            <strong>
              {page === "workbench"
                ? t("계면 분석")
                : page === "engines"
                  ? t("계산 엔진")
                  : t("계산 작업")}
            </strong>
          </div>
          <div className="topbar-controls">
            <div
              className="language-switch"
              role="group"
              aria-label={t("언어")}
            >
              {(["ko", "en"] as const).map((code) => (
                <button
                  type="button"
                  key={code}
                  lang={code}
                  aria-pressed={language === code}
                  onClick={() => setLanguage(code)}
                >
                  {code === "ko" ? "한국어" : "English"}
                </button>
              ))}
            </div>
            <div className="local-badge">
              <i />
              {t("로컬 실행")}
            </div>
          </div>
        </header>
        {error && (
          <div className="alert error" role="alert">
            {message(error)}
            <button aria-label={t("오류 닫기")} onClick={() => setError("")}>
              <X size={17} />
            </button>
          </div>
        )}
        {notice && (
          <div className="alert notice" role="status">
            {message(notice)}
            <button aria-label={t("알림 닫기")} onClick={() => setNotice("")}>
              <X size={17} />
            </button>
          </div>
        )}
        {page === "workbench" && (
          <div className="page-content">
            <div className="page-title">
              <div>
                <h1>{analysis ? analysis.name : t("새 계면 분석")}</h1>
                <p>
                  {analysis
                    ? t(
                        "파트너 {0} ↔ {1} · 중원자 거리 {2} Å",
                        analysis.input.group1.join("+"),
                        analysis.input.group2.join("+"),
                        analysis.input.cutoff,
                      )
                    : t(
                        "복합체 구조에서 계면을 찾고, 여러 계산 도구의 결과를 함께 비교하세요.",
                      )}
                </p>
              </div>
              <button
                className="button secondary"
                onClick={() => input.current?.click()}
                disabled={busy}
              >
                <FileUp size={16} /> {t("PDB 불러오기")}
              </button>
              <input
                ref={input}
                hidden
                type="file"
                accept=".pdb,.ent"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    act(async () => {
                      if (file.size > 20000000)
                        throw Error("20 MB 이하의 PDB를 선택하세요.");
                      setupSource(
                        await api<StructureInfo>("/structures", "POST", {
                          name: file.name,
                          pdb: await file.text(),
                        }),
                      );
                    });
                  e.target.value = "";
                }}
              />
            </div>
            {source && (
              <section className="panel setup-panel">
                <div className="panel-heading">
                  <div>
                    <h2>{t("분석할 계면 선택")}</h2>
                  </div>
                  <button
                    aria-label={t("설정 닫기")}
                    onClick={() => setSource(null)}
                  >
                    <X size={18} />
                  </button>
                </div>
                <p className="muted">
                  {source.name} ·{" "}
                  {t(
                    "모델 수 {0} · 원본 잔기 번호를 보존합니다.",
                    source.models.length,
                  )}
                </p>
                <div className="setup-grid">
                  <label>
                    {t("구조 모델")}{" "}
                    <select
                      value={model}
                      onChange={(e) => {
                        const m = source.models.find(
                          (m) => m.index === +e.target.value,
                        )!;
                        setModel(m.index);
                        setG1(m.chains.slice(0, 1).map((c) => c.id));
                        setG2(m.chains.slice(1, 2).map((c) => c.id));
                        setScan(m.chains.slice(0, 1).map((c) => c.id));
                      }}
                    >
                      {source.models.map((m) => (
                        <option key={m.index} value={m.index}>
                          {t(
                            "모델 {0} · 체인 수 {1}",
                            m.serial,
                            m.chains.length,
                          )}
                        </option>
                      ))}
                    </select>
                  </label>
                  {[
                    [t("파트너 1"), g1, setG1],
                    [t("파트너 2"), g2, setG2],
                    [t("변이 대상 체인"), scan, setScan],
                  ].map(([label, values, setter]) => (
                    <div key={String(label)}>
                      <label>{String(label)}</label>
                      <div className="chain-picker">
                        {source.models
                          .find((m) => m.index === model)
                          ?.chains.map((c) => (
                            <button
                              key={c.id}
                              className={
                                (values as string[]).includes(c.id)
                                  ? "chosen"
                                  : ""
                              }
                              onClick={() =>
                                toggleChain(
                                  c.id,
                                  values as string[],
                                  setter as (s: string[]) => void,
                                )
                              }
                            >
                              {c.id.trim() || "∅"}
                              <small>{c.count} aa</small>
                            </button>
                          ))}
                      </div>
                    </div>
                  ))}
                  <label>
                    {t("계면 cutoff (Å)")}{" "}
                    <input
                      type="number"
                      min="2"
                      max="12"
                      step="0.5"
                      value={cutoff}
                      onChange={(e) => setCutoff(+e.target.value)}
                    />
                  </label>
                </div>
                <div className="setup-footer">
                  <label className="checkline">
                    <input
                      type="checkbox"
                      checked={gly}
                      onChange={(e) => setGly(e.target.checked)}
                    />{" "}
                    {t("Gly→Ala 포함 (측쇄 제거 변이와 구분)")}
                  </label>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={create}
                  >
                    {t("계면 확인")} <ArrowRight size={16} />
                  </button>
                </div>
                {source.warnings.map((w) => (
                  <p className="warning-text" key={message(w)}>
                    {message(w)}
                  </p>
                ))}
              </section>
            )}
            {!analysis && !source && (
              <>
                <section className="welcome-grid">
                  <div
                    className="upload-card"
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      const file = e.dataTransfer.files[0];
                      if (file)
                        act(async () => {
                          if (file.size > 20000000)
                            throw Error("20 MB 이하 파일만 지원합니다.");
                          setupSource(
                            await api<StructureInfo>("/structures", "POST", {
                              name: file.name,
                              pdb: await file.text(),
                            }),
                          );
                        });
                    }}
                  >
                    <div className="upload-icon">
                      <FileUp size={30} />
                    </div>
                    <h2>{t("복합체 PDB를 불러오세요")}</h2>
                    <p>
                      {t("파일을 여기에 놓거나 선택하세요.")} <br />
                      {t("파트너 체인을 지정하면 계면 후보를 찾아드립니다.")}
                    </p>
                    <button
                      className="button primary"
                      onClick={() => input.current?.click()}
                      disabled={busy}
                    >
                      {t("PDB 파일 선택")} <Plus size={16} />
                    </button>
                    <span className="file-hint">
                      {t(".PDB / .ENT · 최대 20 MB · 로컬 처리")}
                    </span>
                  </div>
                  <div className="example-card">
                    <h2>{t("예제 구조로 둘러보기")}</h2>
                    <p>
                      {t("1JTG · A–B 복합체")}
                      <br />
                      {t("Flex ddG 공식 튜토리얼의 구조입니다.")} <br />
                      {t("예측 점수는 실제 엔진 실행 후 표시됩니다.")}
                    </p>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        act(async () =>
                          setupSource(
                            await api<StructureInfo>("/example", "POST"),
                          ),
                        )
                      }
                    >
                      {t("예제 불러오기")} <ArrowRight size={16} />
                    </button>
                  </div>
                </section>
                <section className="engine-overview">
                  <div className="section-heading">
                    <h2>{t("계산 엔진")}</h2>
                    <button
                      className="text-button"
                      onClick={() => setPage("engines")}
                    >
                      {t("엔진 설정")} <ArrowRight size={15} />
                    </button>
                  </div>
                  <div className="engine-cards">
                    {engines.map((e) => (
                      <div className="mini-engine" key={e.id}>
                        <strong>{e.name}</strong>
                        <span className={"status-dot " + e.status}>
                          {t(STATUS[e.status] ?? e.status)}
                        </span>
                        <small>
                          {e.id === "flex_ddg"
                            ? t("선택 후보 후속 분석")
                            : e.id === "budealascan"
                              ? t("선택적 계면 비교")
                              : t("기본 계면 분석")}
                        </small>
                      </div>
                    ))}
                  </div>
                </section>
              </>
            )}
            {analysis && (
              <>
                <div className="metrics">
                  <Metric
                    label={t("계면 잔기")}
                    value={String(rows.filter((r) => r.interface).length)}
                    caption={t("선택한 파트너 사이의 접촉")}
                  />
                  <Metric
                    label={t("선택한 변이")}
                    value={String(selection.size)}
                    caption={t("단일 alanine 변이 대상")}
                  />
                  <Metric
                    label={t("사용 가능한 엔진")}
                    value={`${engines.filter((e) => e.status === "ready").length} / 4`}
                    caption={t("시험 계산을 통과한 엔진")}
                  />
                  <Metric
                    label={t("완료된 작업")}
                    value={`${jobs.filter((j) => j.status === "succeeded").length} / ${jobs.length}`}
                    caption={t("부분 결과도 즉시 확인")}
                  />
                </div>
                <div className="analysis-grid">
                  <section
                    id="structure-panel"
                    className="panel structure-panel"
                  >
                    <div className="panel-heading">
                      <div>
                        <h2>{t("복합체 구조")}</h2>
                        <span className="subtle-badge">3D / Mol*</span>
                      </div>
                      <span className="muted">
                        {t("드래그 회전 · 휠 확대")}
                      </span>
                    </div>
                    <Suspense
                      fallback={
                        <div className="viewer-message">
                          {t("3D 모듈 불러오는 중…")}
                        </div>
                      }
                    >
                      <StructureViewer
                        id={analysis.id}
                        selected={focusedRow}
                        onSelect={setFocused}
                        mapping={analysis.mapping}
                      />
                    </Suspense>
                    <div className="structure-caption">
                      <span>
                        {t("파트너 1")} · {analysis.input.group1.join("+")}
                      </span>
                      <span>
                        {t("파트너 2")} · {analysis.input.group2.join("+")}
                      </span>
                      <small>{t("선택 잔기 강조 / 엔진용 재번호 구조")}</small>
                    </div>
                  </section>
                  <section className="panel run-panel">
                    <div className="panel-heading">
                      <h2>{t("계산 실행")}</h2>
                    </div>
                    <p className="muted">
                      {t("같은 변이에 대한 결합 변화를 비교합니다.")}
                    </p>
                    <div className="run-engines">
                      {engines
                        .filter((e) => e.id !== "flex_ddg")
                        .map((e) => (
                          <label
                            key={e.id}
                            className={e.status === "ready" ? "" : "disabled"}
                          >
                            <input
                              type="checkbox"
                              checked={engineSelection.includes(e.id)}
                              onChange={() =>
                                setEngineSelection((s) =>
                                  s.includes(e.id)
                                    ? s.filter((x) => x !== e.id)
                                    : [...s, e.id],
                                )
                              }
                              disabled={
                                e.status !== "ready" ||
                                (e.id === "saambe3d" && !twoChainPartners)
                              }
                            />
                            <span>
                              <strong>{e.name}</strong>
                              <small>
                                {e.id === "saambe3d" && !twoChainPartners
                                  ? t("파트너별 체인 1개 필요")
                                  : t(STATUS[e.status] ?? e.status)}
                              </small>
                            </span>
                            {e.status === "ready" ? (
                              <Check size={16} />
                            ) : (
                              <button
                                onClick={(ev) => {
                                  ev.preventDefault();
                                  setPage("engines");
                                }}
                              >
                                {t("설정")}
                              </button>
                            )}
                          </label>
                        ))}
                    </div>
                    <div className="inline-inputs">
                      <label>
                        {t("반복 수")}{" "}
                        <input
                          type="number"
                          min="1"
                          max="50"
                          value={singleScan ? 1 : repeats}
                          disabled={singleScan}
                          onChange={(e) => setRepeats(+e.target.value)}
                        />
                      </label>
                      <label>
                        {t("작업 제한 (초)")}{" "}
                        <input
                          type="number"
                          min="30"
                          max="604800"
                          value={timeout}
                          onChange={(e) => setTimeoutValue(+e.target.value)}
                        />
                      </label>
                    </div>
                    <button
                      className="button primary full"
                      disabled={
                        busy ||
                        !selection.size ||
                        !engineSelection.length ||
                        engineSelection.some(
                          (id) =>
                            engines.find((e) => e.id === id)?.status !==
                            "ready",
                        )
                      }
                      onClick={() => start()}
                    >
                      <Play size={16} /> {t("{0}개 잔기 계산", selection.size)}
                    </button>
                    <div className="flex-section">
                      <strong>{t("Flex ddG 후속 분석")}</strong>
                      <p>{t("선택한 잔기에 ensemble 계산을 추가합니다.")}</p>
                      <label className="compact-label">
                        {t("Ensemble 수")}{" "}
                        <input
                          aria-label={t("Flex ddG 반복 수")}
                          type="number"
                          min="1"
                          max="50"
                          value={flexRepeats}
                          onChange={(e) => setFlexRepeats(+e.target.value)}
                        />
                      </label>
                      {flexRepeats < 35 && (
                        <small className="warning-text">
                          {t("축소 반복: 공식 권장 35회보다 적습니다.")}
                        </small>
                      )}
                      <button
                        className="button secondary full"
                        disabled={
                          busy ||
                          !selection.size ||
                          engines.find((e) => e.id === "flex_ddg")?.status !==
                            "ready"
                        }
                        onClick={() => start(true)}
                      >
                        {t("선택 후보 추가 분석")} <ArrowRight size={15} />
                      </button>
                    </div>
                  </section>
                </div>
                <section className="panel sequence-panel">
                  <div className="panel-heading">
                    <h2>{t("서열 및 잔기 선택")}</h2>
                    <span className="muted">
                      {t("원본 PDB 번호 · 클릭하면 구조에서 확인")}
                    </span>
                  </div>
                  {analysis.input.scan_chains.map((c) => (
                    <div className="sequence-chain" key={c}>
                      <strong>
                        {t("체인")} {c.trim() || "∅"}
                      </strong>
                      <div>
                        {rows
                          .filter((r) => r.chain === c)
                          .map((r) => (
                            <button
                              key={r.key}
                              title={`${residueLabel(r)} · ${r.name}`}
                              className={`${r.interface ? "contact" : ""} ${focused === r.key ? "focused" : ""}`}
                              onClick={() => setFocused(r.key)}
                            >
                              {r.wt}
                              <small>
                                {r.number}
                                {r.icode}
                              </small>
                            </button>
                          ))}
                      </div>
                    </div>
                  ))}
                </section>
                <section className="panel results-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>{t("잔기별 계산 결과")}</h2>
                      <span className="subtle-badge">
                        {t("잔기 수 {0}", visible.length)}
                      </span>
                    </div>
                    <div className="export-actions">
                      <a
                        className="button secondary small"
                        href={`/api/analyses/${analysis.id}/export.csv`}
                      >
                        <Download size={14} /> CSV
                      </a>
                      <a
                        className="button secondary small"
                        href={`/api/analyses/${analysis.id}/export.zip`}
                      >
                        <Database size={14} /> {t("전체 기록")}
                      </a>
                    </div>
                  </div>
                  <div className="results-toolbar">
                    <div className="searchbox">
                      <Search size={16} />
                      <input
                        aria-label={t("잔기 검색")}
                        placeholder={t("잔기 검색 · A:Y100")}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </div>
                    <select
                      aria-label={t("잔기 필터")}
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    >
                      <option value="interface">{t("계면 잔기")}</option>
                      <option value="all">{t("전체 잔기 / 수동 후보")}</option>
                      <option value="selected">{t("선택한 잔기")}</option>
                      <option value="consensus">{t("합의 후보")}</option>
                    </select>
                    <select
                      aria-label={t("정렬")}
                      value={sort}
                      onChange={(e) => setSort(e.target.value)}
                    >
                      <option value="position">{t("잔기 번호순")}</option>
                      <option value="distance">{t("거리순")}</option>
                      <option value="support">{t("지지 수순")}</option>
                    </select>
                    <div className="segmented">
                      <button
                        className={view === "table" ? "on" : ""}
                        onClick={() => setView("table")}
                      >
                        {t("표")}
                      </button>
                      <button
                        className={view === "heatmap" ? "on" : ""}
                        onClick={() => setView("heatmap")}
                      >
                        {t("히트맵")}
                      </button>
                    </div>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>
                            <input
                              aria-label={t("표시된 계산 가능 잔기 전체 선택")}
                              type="checkbox"
                              checked={
                                visible.some((r) => r.eligible) &&
                                visible
                                  .filter((r) => r.eligible)
                                  .every((r) => selection.has(r.key))
                              }
                              onChange={(e) => {
                                const on = e.target.checked;
                                setSelection((s) => {
                                  const n = new Set(s);
                                  visible
                                    .filter((r) => r.eligible)
                                    .forEach((r) =>
                                      on ? n.add(r.key) : n.delete(r.key),
                                    );
                                  return n;
                                });
                              }}
                            />
                          </th>
                          <th>{t("잔기")}</th>
                          <th>{t("거리")}</th>
                          {ENGINES.map((e) => (
                            <th key={e}>
                              {NAMES[e]}
                              <small>
                                {e === "saambe3d"
                                  ? t("예측 ΔΔG · kcal/mol")
                                  : units[e]}
                              </small>
                            </th>
                          ))}
                          <th>
                            {t("합의 판정")}
                            <small>{t("지지 / 판정 / 선택")}</small>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map((r) => (
                          <tr
                            key={r.key}
                            className={focused === r.key ? "row-focused" : ""}
                            onClick={() => setFocused(r.key)}
                          >
                            <td>
                              <input
                                aria-label={t("{0} 계산 선택", residueLabel(r))}
                                type="checkbox"
                                disabled={!r.eligible}
                                checked={selection.has(r.key)}
                                onChange={() => toggle(r.key)}
                                onClick={(e) => e.stopPropagation()}
                              />
                            </td>
                            <td>
                              <strong>
                                {r.chain.trim() || "∅"}:{r.wt}
                                {r.number}
                                {r.icode}
                              </strong>
                              <small>
                                {r.eligible
                                  ? "→ ALA"
                                  : r.wt === "A"
                                    ? t("원래 alanine")
                                    : r.wt === "G"
                                      ? t("Gly 제외")
                                      : t("구조 확인 필요")}
                              </small>
                            </td>
                            <td className="mono">
                              {r.distance === null
                                ? "—"
                                : `${r.distance.toFixed(2)} Å`}
                            </td>
                            {ENGINES.map((e) => {
                              const s = r.scores[e];
                              return (
                                <td
                                  key={e}
                                  className={
                                    view === "heatmap" && s?.value != null
                                      ? "heat-cell"
                                      : ""
                                  }
                                  style={
                                    view === "heatmap" && s?.value != null
                                      ? {
                                          background:
                                            s.value > 0
                                              ? `rgba(198,147,69,${Math.min(0.4, 0.035 + Math.abs(s.value) / (e === "flex_ddg" ? 20 : 8))})`
                                              : `rgba(77,128,176,${Math.min(0.4, 0.035 + Math.abs(s.value) / 8)})`,
                                        }
                                      : undefined
                                  }
                                >
                                  {scoreCell(s)}
                                </td>
                              );
                            })}
                            <td>
                              <span
                                className={
                                  r.consensus ? "consensus-pill" : "muted"
                                }
                              >
                                {r.eligible_count
                                  ? `${r.support_count} / ${r.eligible_count} / ${r.selected_count}`
                                  : t("기준 미설정")}
                              </span>
                              {r.provisional && <small>{t("부분 결과")}</small>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!visible.length && (
                      <div className="empty-panel">
                        {t(
                          "해당 조건의 잔기가 없습니다. 파트너·거리·필터를 확인하세요.",
                        )}
                      </div>
                    )}
                  </div>
                  <div className="table-note">
                    <span>
                      <i className="legend-dot orange" />
                      {t("양수 = 변이에 따른 결합 약화")}
                    </span>
                    <span>{t("— 미실행 · 점수 척도 간 단순 평균 없음")}</span>
                    {view === "heatmap" && (
                      <span>
                        {t(
                          "색상 강도는 도구별 척도이며 직접 비교하지 않습니다.",
                        )}
                      </span>
                    )}
                  </div>
                </section>
                <Suspense
                  fallback={
                    <section className="panel analytics-message">
                      {t("결과 해석을 불러오고 있습니다…")}
                    </section>
                  }
                >
                  <AnalyticsPanel
                    key={analysis.id}
                    analysis={analysis}
                    jobs={jobs}
                    focused={focused}
                    onSelect={setFocused}
                    onThreshold={(engine, value) => {
                      setThresholdEngine(engine);
                      setThreshold(String(value));
                      setEvidence("");
                      document
                        .getElementById("threshold-panel")
                        ?.scrollIntoView({
                          behavior: "smooth",
                          block: "center",
                        });
                    }}
                  />
                </Suspense>
                <div className="bottom-grid">
                  <section className="panel detail-panel">
                    <div className="panel-heading">
                      <h2>
                        {focusedRow ? residueLabel(focusedRow) : t("잔기 상세")}
                      </h2>
                    </div>
                    {focusedRow ? (
                      <>
                        <p>
                          {focusedRow.name} {t("→ ALA · 원본")}{" "}
                          {focusedRow.chain}:{focusedRow.number}
                          {focusedRow.icode} {t("/ 엔진")}{" "}
                          {focusedRow.engine_chain}:{focusedRow.engine_number}
                        </p>
                        {focusedRow.warnings.map((w) => (
                          <p className="warning-text" key={message(w)}>
                            {message(w)}
                          </p>
                        ))}
                        {Object.entries(focusedRow.scores).map(([e, s]) => (
                          <details key={e}>
                            <summary>
                              {NAMES[e]} · {s.completed}/{s.planned}{" "}
                              {t("완료 ·")} {s.unit || t("결과 대기")}
                            </summary>
                            <pre>
                              {JSON.stringify(
                                s.details,
                                (key, value) =>
                                  key === "unit_note" &&
                                  typeof value === "string"
                                    ? message(value)
                                    : value,
                                2,
                              )}
                            </pre>
                            {s.jobs.map((j) => (
                              <button
                                className="text-button"
                                key={j}
                                onClick={() =>
                                  act(async () =>
                                    setLog(
                                      (
                                        await api<{ text: string }>(
                                          `/jobs/${j}/logs`,
                                        )
                                      ).text || "아직 로그가 없습니다.",
                                    ),
                                  )
                                }
                              >
                                {t("실행 로그")} {j.slice(0, 6)}
                              </button>
                            ))}
                          </details>
                        ))}
                      </>
                    ) : (
                      <p className="muted">
                        {t(
                          "표 또는 서열에서 잔기를 선택하면 원시 점수와 계산 근거를 확인할 수 있습니다.",
                        )}
                      </p>
                    )}
                  </section>
                  <section
                    id="threshold-panel"
                    className="panel threshold-panel"
                  >
                    <div className="panel-heading">
                      <h2>{t("합의 판정 기준")}</h2>
                    </div>
                    <p className="muted">
                      {t(
                        "검증 근거가 있는 엔진별 기준을 입력하세요. 미설정 엔진은 점수만 표시하며 합의 판정에서 제외합니다.",
                      )}
                    </p>
                    <div className="inline-inputs">
                      <label>
                        {t("엔진")}{" "}
                        <select
                          value={thresholdEngine}
                          onChange={(e) => {
                            setThresholdEngine(e.target.value);
                            const t = analysis.thresholds[e.target.value];
                            setThreshold(t?.value?.toString() || "");
                            setEvidence(t?.evidence || "");
                          }}
                        >
                          {ENGINES.map((e) => (
                            <option key={e} value={e}>
                              {NAMES[e]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        {t("임계값 ·")} {units[thresholdEngine]}
                        <input
                          type="number"
                          placeholder={t("미설정")}
                          value={threshold}
                          onChange={(e) => setThreshold(e.target.value)}
                        />
                      </label>
                    </div>
                    <label>
                      {t("검증 근거 / 프로토콜")}{" "}
                      <input
                        placeholder={t("평가 데이터, 참고 문헌, 적용 조건")}
                        value={evidence}
                        onChange={(e) => setEvidence(e.target.value)}
                      />
                    </label>
                    <button
                      className="button secondary"
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          const a = await api<Analysis>(
                            `/analyses/${analysis.id}/threshold`,
                            "PUT",
                            {
                              engine: thresholdEngine,
                              value:
                                threshold === "" ? null : Number(threshold),
                              unit: units[thresholdEngine],
                              evidence,
                            },
                          );
                          setAnalysis(a);
                          setRows(
                            (
                              await api<{ rows: ResultRow[] }>(
                                `/analyses/${a.id}/results`,
                              )
                            ).rows,
                          );
                          setNotice("사용자 지정 판정 기준을 저장했습니다.");
                        })
                      }
                    >
                      {t("기준 저장")}
                    </button>
                  </section>
                </div>
                <details className="preparation-notes">
                  <summary>
                    {t("구조 전처리 기록 ·")} {analysis.warnings.length}
                    {t("개 항목")}
                  </summary>
                  {analysis.warnings.map((w, i) => (
                    <p key={i}>{message(w)}</p>
                  ))}
                  {!!analysis.blocking_hetero.length && (
                    <p className="warning-text">
                      {t(
                        "비표준 잔기/보조인자가 있어 실행이 차단됩니다. 원본을 확인해 주세요.",
                      )}
                    </p>
                  )}
                </details>
              </>
            )}
          </div>
        )}
        {page === "engines" && (
          <div className="page-content">
            <div className="page-title">
              <div>
                <h1>{t("계산 엔진 설치")}</h1>
                <p>
                  {t(
                    "앱에서 도구를 설치하고 실제 예제 계산으로 실행 준비를 확인합니다.",
                  )}
                </p>
              </div>
            </div>
            <div className="runtime-panel panel">
              <ShieldCheck size={24} />
              <div>
                <strong>{t("이 컴퓨터에서 계산합니다.")}</strong>
                <p>
                  {t(
                    "기능 검증은 설치·실행·파싱 확인이며 예측 정확도 검증과는 다릅니다.",
                  )}
                </p>
              </div>
              <label>
                {t("동시 작업 수")}{" "}
                <input
                  type="number"
                  min="1"
                  max="8"
                  value={concurrency}
                  onChange={(e) => setConcurrency(+e.target.value)}
                />
              </label>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await api("/runtime", "PUT", { concurrency });
                    setNotice("동시 실행 설정을 저장했습니다.");
                  })
                }
              >
                {t("저장")}
              </button>
            </div>
            <div className="settings-grid">
              {engines.map((e) => (
                <EngineCard
                  key={`${e.id}-${e.executable}`}
                  engine={e}
                  busy={busy}
                  active={running.some((j) => j.engine === e.id)}
                  onInstall={(file) =>
                    act(async () => {
                      if (file) {
                        if (file.size > 8 * 1024 ** 3)
                          throw Error(
                            "배포 파일은 최대 8 GB입니다. 큰 패키지는 고급 설정에서 연결하세요.",
                          );
                        setNotice(
                          "배포 파일을 이 컴퓨터의 설치 폴더로 복사하고 있습니다…",
                        );
                        const response = await fetch(
                          `/api/engines/${e.id}/install-archive`,
                          {
                            method: "POST",
                            headers: {
                              "X-Hotspot-Client": "local-ui",
                              "Content-Type": "application/octet-stream",
                            },
                            body: file,
                          },
                        );
                        if (!response.ok) {
                          const result = await response.json();
                          throw Error(
                            result.detail || "설치 요청에 실패했습니다.",
                          );
                        }
                      } else {
                        await api(`/engines/${e.id}/install`, "POST");
                      }
                      await refresh();
                      setNotice(
                        "설치를 시작했습니다. 설치 후 시험 계산이 자동으로 실행됩니다. 계산 작업에서 진행 상황을 확인하세요.",
                      );
                    })
                  }
                  onSave={(body) =>
                    act(async () => {
                      await api(`/engines/${e.id}`, "PUT", body);
                      await refresh();
                      setNotice(
                        `${e.name} 설정을 저장했습니다. 실제 시험 계산을 실행하세요.`,
                      );
                    })
                  }
                  onValidate={() =>
                    act(async () => {
                      await api(`/engines/${e.id}/validate`, "POST");
                      await refresh();
                      setNotice(
                        "1JTG 예제로 실제 시험 계산을 시작했습니다. 계산 작업에서 진행 상황을 확인하세요.",
                      );
                    })
                  }
                />
              ))}
            </div>
            <p className="muted">
              {t(
                "FoldX·Rosetta 배포 파일은 각 도구의 이용 조건에 따라 공식 사이트에서 받으세요. BudeAlaScan은 로컬 Docker 이미지 연결을 지원합니다.",
              )}
            </p>
          </div>
        )}
        {page === "jobs" && (
          <div className="page-content">
            <div className="page-title">
              <div>
                <h1>{t("계산 작업")}</h1>
                <p>
                  {t("브라우저를 이동해도 계산은 로컬 worker에서 계속됩니다.")}
                </p>
              </div>
              <span className="subtle-badge">
                {t("진행 중인 작업 {0}개", running.length)}
              </span>
            </div>
            <div className="panel jobs-panel">
              {!allJobs.length && (
                <div className="empty-panel">
                  {t(
                    "아직 등록된 작업이 없습니다. 엔진 설정에서 시험 계산을 시작하세요.",
                  )}
                </div>
              )}
              {allJobs.map((j) => (
                <div className="job-row" key={j.id}>
                  <div className={"job-icon " + j.status}>
                    {j.status === "running" ? (
                      <LoaderCircle className="spin" size={19} />
                    ) : j.status === "succeeded" ? (
                      <Check size={19} />
                    ) : (
                      <FlaskConical size={19} />
                    )}
                  </div>
                  <div className="job-description">
                    <strong>
                      {NAMES[j.engine]}{" "}
                      <span>
                        {j.payload.install
                          ? t("자동 설치")
                          : j.payload.validation
                            ? t("설치 검증")
                            : j.payload.residues.length === 1
                              ? residueLabel(j.payload.residues[0])
                              : t("{0}개 잔기", j.payload.residues.length)}
                      </span>
                    </strong>
                    <small>
                      {j.id.slice(0, 8)} {t("· 반복")} {j.payload.repeat}/
                      {j.payload.planned_repeats} ·{" "}
                      {new Date(j.created * 1000).toLocaleString(language)}
                    </small>
                    {j.error && (
                      <p className="warning-text">{message(j.error)}</p>
                    )}
                  </div>
                  <span className={"status-dot " + j.status}>
                    {j.cancel && j.status === "running"
                      ? t("취소 중")
                      : t(STATUS[j.status] ?? j.status)}
                  </span>
                  <button
                    className="button secondary small"
                    onClick={() =>
                      act(async () =>
                        setLog(
                          (await api<{ text: string }>(`/jobs/${j.id}/logs`))
                            .text || "아직 로그가 없습니다.",
                        ),
                      )
                    }
                  >
                    {t("로그")}
                  </button>
                  {["running", "queued"].includes(j.status) ? (
                    <button
                      aria-label={t("작업 취소")}
                      className="icon-button"
                      disabled={busy || !!j.cancel}
                      onClick={() =>
                        act(async () => {
                          await api(`/jobs/${j.id}/cancel`, "POST");
                          await refresh();
                        })
                      }
                    >
                      <Square size={15} />
                    </button>
                  ) : ["failed", "cancelled"].includes(j.status) ? (
                    <button
                      aria-label={t("작업 재시도")}
                      className="icon-button"
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await api(`/jobs/${j.id}/retry`, "POST");
                          await refresh();
                        })
                      }
                    >
                      <RotateCcw size={16} />
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        )}
        <footer className="page-footer">
          <span>HotspotFinder</span>
          <span>{t("예측 후보의 비교를 위한 도구 · 실험적 검증 필요")}</span>
        </footer>
      </main>
      {log !== null && (
        <div className="modal-backdrop" onClick={() => setLog(null)}>
          <section
            className="log-modal"
            role="dialog"
            aria-modal="true"
            aria-label={t("계산 로그")}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-heading">
              <h2>{t("계산 로그")}</h2>
              <button aria-label={t("로그 닫기")} onClick={() => setLog(null)}>
                <X size={20} />
              </button>
            </div>
            <pre>{log === "아직 로그가 없습니다." ? t(log) : log}</pre>
          </section>
        </div>
      )}
      {busy && (
        <div className="busy-toast" role="status">
          <LoaderCircle className="spin" size={16} /> {t("처리 중…")}
        </div>
      )}
    </div>
  );
}
function Metric({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{caption}</small>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <LanguageProvider>
    <App />
  </LanguageProvider>,
);
