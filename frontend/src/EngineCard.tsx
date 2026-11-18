import { useLanguage } from "./i18n";
import { useRef, useState } from "react";
import { Download, FileUp, LoaderCircle, Play } from "lucide-react";
import { Engine, STATUS } from "./types";

type Props = {
  engine: Engine;
  busy: boolean;
  active: boolean;
  onSave: (body: unknown) => void;
  onValidate: () => void;
  onInstall: (file?: File) => void;
};

export default function EngineCard({
  engine,
  busy,
  active,
  onSave,
  onValidate,
  onInstall,
}: Props) {
  const { t, message } = useLanguage();
  const [path, setPath] = useState(engine.executable);
  const [version, setVersion] = useState(engine.version);
  const [data, setData] = useState(engine.data_dir);
  const [image, setImage] = useState(engine.image);
  const input = useRef<HTMLInputElement>(null);
  const disabled = busy || active;
  const unchanged =
    path === engine.executable &&
    version === engine.version &&
    data === engine.data_dir &&
    image === engine.image;
  const descriptions = {
    saambe3d: t(
      "두 체인 사이의 결합 ΔΔG를 CPU로 예측합니다. 선택한 잔기를 한 번에 계산하며 설치 후 예제로 검증합니다.",
    ),
    evoef: t(
      "공개 소스를 내려받아 이 컴퓨터에 설치합니다. C++ 컴파일러와 Git이 필요하며 설치 후 예제 계산으로 자동 검증합니다.",
    ),
    foldx: t(
      "공식 사이트에서 이 컴퓨터용 배포 파일을 받은 뒤 선택하세요. 앱이 압축을 풀고 실행 파일을 찾아 시험 계산까지 진행합니다.",
    ),
    flex_ddg: t(
      "Rosetta 실행 파일과 database가 포함된 이 컴퓨터용 배포 파일을 선택하세요. 앱이 설치하고 Flex ddG 예제 계산을 진행합니다.",
    ),
    budealascan: t(
      "BudeAlaScan이 설치된 로컬 Docker 이미지를 연결하세요. Docker와 SCWRL을 포함한 이미지 준비가 필요합니다.",
    ),
  };
  const links = {
    foldx: "https://foldxsuite.crg.eu/licensing-and-services",
    flex_ddg: "https://rosettacommons.org/software/download/",
    budealascan: "https://github.com/wells-wood-research/BAlaS",
  };

  return (
    <section className="panel engine-config">
      <div className="panel-heading">
        <h2>{engine.name}</h2>
        <span className={"status-dot " + (active ? "running" : engine.status)}>
          {active
            ? t("작업 진행 중")
            : t(STATUS[engine.status] ?? engine.status)}
        </span>
      </div>
      <p className="muted">{descriptions[engine.id]}</p>
      <div className="engine-actions">
        {engine.id === "evoef" || engine.id === "saambe3d" ? (
          <button
            className="button primary"
            disabled={disabled}
            onClick={() => onInstall()}
          >
            {active ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Download size={16} />
            )}
            {engine.executable
              ? t("자동 재설치 및 검증")
              : t("자동 설치 및 검증")}
          </button>
        ) : (
          <a
            className="button secondary"
            href={links[engine.id]}
            target="_blank"
            rel="noreferrer"
          >
            {t("공식 배포 안내")}
          </a>
        )}
        {["foldx", "flex_ddg"].includes(engine.id) && (
          <>
            <input
              ref={input}
              type="file"
              accept=".zip,.tar,.gz,.bz2,.xz,.tgz"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onInstall(file);
                event.target.value = "";
              }}
            />
            <button
              className="button primary"
              disabled={disabled}
              onClick={() => input.current?.click()}
            >
              <FileUp size={16} /> {t("배포 파일로 설치")}
            </button>
          </>
        )}
      </div>
      {active && (
        <p role="status" className="validation-note">
          {t("계산 작업 화면에서 진행 상황과 로그를 확인할 수 있습니다.")}
        </p>
      )}
      <details className="advanced-settings">
        <summary>{t("고급 설정 · 기존 설치 연결")}</summary>
        <label>
          {engine.id === "budealascan"
            ? t("Docker 실행 파일 절대 경로")
            : engine.id === "saambe3d"
              ? t("전용 Python 실행 파일 절대 경로")
              : t("실행 파일 절대 경로")}
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="/absolute/path/to/executable"
          />
        </label>
        <label>
          {t("버전 / 빌드 식별자")}{" "}
          <input
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder={t("버전 및 소스 revision")}
          />
        </label>
        {engine.id === "budealascan" ? (
          <label>
            {t("로컬 Docker 이미지 ID")}{" "}
            <input
              value={image}
              onChange={(event) => setImage(event.target.value)}
              placeholder="sha256:…"
            />
          </label>
        ) : (
          engine.id !== "evoef" && (
            <label>
              {engine.id === "flex_ddg"
                ? t("Rosetta database 경로")
                : engine.id === "saambe3d"
                  ? t("SAAMBE-3D 모델과 스크립트 폴더")
                  : t("rotabase 등 데이터 폴더 (선택)")}
              <input
                value={data}
                onChange={(event) => setData(event.target.value)}
                placeholder="/path/to/data"
              />
            </label>
          )
        )}
        <div className="engine-actions">
          <button
            className="button secondary"
            disabled={disabled}
            onClick={() =>
              onSave({ executable: path, version, data_dir: data, image })
            }
          >
            {t("설정 저장")}
          </button>
          <button
            className="button primary"
            disabled={disabled || !engine.executable || !unchanged}
            onClick={onValidate}
          >
            <Play size={14} /> {t("실제 시험 계산")}
          </button>
        </div>
      </details>
      <small className="muted">
        {engine.platform} {t("· 실행 파일·프로토콜 변경 시 재검증")}
      </small>
      {engine.error && <p className="warning-text">{message(engine.error)}</p>}
      {engine.validation?.note && (
        <p className="validation-note">{message(engine.validation.note)}</p>
      )}
    </section>
  );
}
