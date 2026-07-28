import { useEffect, useRef, type PointerEvent } from "react";

import { chartConfig } from "@/chart/config";
import { renderChart } from "@/chart/draw";
import { probeFromPointer } from "@/chart/interaction";
import { useChartStore } from "@/store/useChartStore";

export function PsychrometricChart() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const layers = useChartStore((state) => state.layers);
  const points = useChartStore((state) => state.points);
  const probe = useChartStore((state) => state.probe);
  const setProbe = useChartStore((state) => state.setProbe);
  const resetProbe = useChartStore((state) => state.resetProbe);

  // Um quadro inteiro é redesenhado a cada mudança de camada, pontos ou cursor: com
  // ~1500 amostras por curva isso custa poucos milissegundos e dispensa camadas em cache.
  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) {
      return;
    }
    renderChart(ctx, { layers, points, probe });
  }, [layers, points, probe]);

  const handlePointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const estado = probeFromPointer(canvas, event.clientX, event.clientY);
    if (estado) {
      setProbe(estado);
    }
  };

  return (
    <canvas
      ref={canvasRef}
      width={chartConfig.width}
      height={chartConfig.height}
      className="h-auto w-full max-w-[1200px] touch-none border border-gray-300 bg-white"
      onPointerMove={handlePointerMove}
      onPointerLeave={resetProbe}
    />
  );
}
