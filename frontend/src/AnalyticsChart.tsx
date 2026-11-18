import { useEffect, useRef } from "react";
import {
  init,
  use,
  type EChartsCoreOption,
  type EChartsType,
} from "echarts/core";
import { ScatterChart, HeatmapChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EngineId } from "./types";

use([
  ScatterChart,
  HeatmapChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
  CanvasRenderer,
]);
export type ChartDatum = {
  key?: string;
  threshold?: number;
  pair?: [EngineId, EngineId];
};

type Props = {
  option: EChartsCoreOption;
  label: string;
  onPick: (datum: ChartDatum) => void;
};

export default function AnalyticsChart({ option, label, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const handler = useRef(onPick);
  handler.current = onPick;
  useEffect(() => {
    const instance = init(host.current!, undefined, { renderer: "canvas" });
    chart.current = instance;
    instance.on("click", (event) => {
      if (event.data) handler.current(event.data as ChartDatum);
    });
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(host.current!);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption(
      { animation: false, aria: { enabled: true }, ...option },
      { notMerge: true },
    );
  }, [option]);
  return (
    <div className="analytics-chart" ref={host} role="img" aria-label={label} />
  );
}
