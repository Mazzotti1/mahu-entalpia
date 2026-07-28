/**
 * Sistema de coordenadas da carta: TBS (°C) no eixo X, umidade absoluta (g/kg) no Y.
 * As dimensões são as do buffer do canvas; o CSS escala o elemento, e a conversão de
 * coordenadas do mouse compensa essa escala.
 */
export const chartConfig = {
  margin: { top: 60, right: 80, bottom: 80, left: 100 },
  width: 1200,
  height: 760,
  tbsMin: 0,
  tbsMax: 50,
  wMin: 0,
  wMax: 30,
} as const;

export interface PlotBounds {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export function getPlotBounds(): PlotBounds {
  return {
    left: chartConfig.margin.left,
    top: chartConfig.margin.top,
    right: chartConfig.width - chartConfig.margin.right,
    bottom: chartConfig.height - chartConfig.margin.bottom,
  };
}

const plotWidth = chartConfig.width - chartConfig.margin.left - chartConfig.margin.right;
const plotHeight = chartConfig.height - chartConfig.margin.top - chartConfig.margin.bottom;

/** TBS (°C) -> pixel X. */
export function tbsToX(tbs: number): number {
  const escala = (tbs - chartConfig.tbsMin) / (chartConfig.tbsMax - chartConfig.tbsMin);
  return chartConfig.margin.left + escala * plotWidth;
}

/** Umidade absoluta (g/kg) -> pixel Y. */
export function wToY(wGkg: number): number {
  const escala = (wGkg - chartConfig.wMin) / (chartConfig.wMax - chartConfig.wMin);
  return chartConfig.margin.top + (1 - escala) * plotHeight;
}

/** Pixel X -> TBS (°C). */
export function xToTbs(x: number): number {
  const escala = (x - chartConfig.margin.left) / plotWidth;
  return chartConfig.tbsMin + escala * (chartConfig.tbsMax - chartConfig.tbsMin);
}

/** Pixel Y -> umidade absoluta (g/kg). */
export function yToW(y: number): number {
  const escala = 1 - (y - chartConfig.margin.top) / plotHeight;
  return chartConfig.wMin + escala * (chartConfig.wMax - chartConfig.wMin);
}
