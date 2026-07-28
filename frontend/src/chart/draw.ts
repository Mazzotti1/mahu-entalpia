import { chartConfig, getPlotBounds, tbsToX, wToY } from "@/chart/config";
import type { LayerVisibility } from "@/chart/layers";
import {
  calcularEntalpia,
  entalpiaParaW,
  urParaW,
  wDePressaoVapor,
  wDeVolumeEspecifico,
} from "@/lib/psicrometria";
import type { ProbeState, ProcessPoint } from "@/types/chart";

/** Ordem de camadas da §5 do planejamento técnico, do fundo para a frente. */
const CORES = {
  fundo: "#ffffff",
  gradeMenor: "#f1f5f9",
  gradeMaior: "#d1d5db",
  eixo: "#374151",
  rotuloEixo: "#111827",
  rotuloTick: "#6b7280",
  saturacao: "#6b7280",
  umidadeRelativa: "#d1d5db",
  rotuloUmidadeRelativa: "#9ca3af",
  entalpia: "#a7f3d0",
  bulboUmido: "#bae6fd",
  pressaoVapor: "#e5e7eb",
  volumeEspecifico: "#c7d2fe",
  vetorProcesso: "#2563eb",
  pontoProcesso: "#e11d48",
  cursor: "#ef4444",
} as const;

/** Passo de amostragem das curvas em °C: denso o bastante para a linha sair suave. */
const PASSO_CURVA = 0.2;

interface Ponto {
  x: number;
  y: number;
}

/** `null` marca uma quebra na curva (trecho fora da carta ou acima da saturação). */
type Traco = (Ponto | null)[];

export interface ChartScene {
  layers: LayerVisibility;
  points: ProcessPoint[];
  probe: ProbeState | null;
}

/** Desenha um quadro inteiro da carta. Chamar isto substitui o conteúdo do canvas. */
export function renderChart(ctx: CanvasRenderingContext2D, scene: ChartScene): void {
  ctx.clearRect(0, 0, chartConfig.width, chartConfig.height);
  desenharFundo(ctx);
  desenharEixosEGrade(ctx, scene.layers);
  desenharCurvaSaturacao(ctx);
  desenharIsolinhasUmidadeRelativa(ctx, scene.layers);
  desenharIsolinhasEntalpia(ctx, scene.layers);
  desenharIsolinhasBulboUmido(ctx, scene.layers);
  desenharIsolinhasPressaoVapor(ctx, scene.layers);
  desenharIsolinhasVolumeEspecifico(ctx, scene.layers);
  desenharVetorProcesso(ctx, scene.points);
  desenharPontosProcesso(ctx, scene.points);
  if (scene.probe) {
    desenharCursor(ctx, scene.probe);
  }
}

function desenharFundo(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = CORES.fundo;
  ctx.fillRect(0, 0, chartConfig.width, chartConfig.height);
}

function desenharEixosEGrade(ctx: CanvasRenderingContext2D, layers: LayerVisibility): void {
  const plot = getPlotBounds();
  ctx.lineWidth = 1;
  ctx.font = "12px Segoe UI";
  ctx.fillStyle = CORES.rotuloTick;

  if (layers.dryBulb) {
    for (let t = chartConfig.tbsMin; t <= chartConfig.tbsMax; t += 1) {
      const x = tbsToX(t);
      const principal = t % 5 === 0;
      ctx.beginPath();
      ctx.strokeStyle = principal ? CORES.gradeMaior : CORES.gradeMenor;
      ctx.moveTo(x, plot.top);
      ctx.lineTo(x, plot.bottom);
      ctx.stroke();
      if (principal) {
        ctx.fillText(String(t), x - 6, plot.bottom + 20);
      }
    }
  }

  if (layers.humidityRatio) {
    for (let w = chartConfig.wMin; w <= chartConfig.wMax; w += 1) {
      const y = wToY(w);
      const principal = w % 5 === 0;
      ctx.beginPath();
      ctx.strokeStyle = principal ? CORES.gradeMaior : CORES.gradeMenor;
      ctx.moveTo(plot.left, y);
      ctx.lineTo(plot.right, y);
      ctx.stroke();
      if (principal) {
        ctx.fillText(String(w), plot.right + 8, y + 4);
      }
    }
  }

  ctx.strokeStyle = CORES.eixo;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.moveTo(plot.left, plot.top);
  ctx.lineTo(plot.left, plot.bottom);
  ctx.lineTo(plot.right, plot.bottom);
  ctx.stroke();

  ctx.fillStyle = CORES.rotuloEixo;
  ctx.font = "14px Segoe UI";
  ctx.fillText("Dry Bulb Temperature (°C)", (plot.left + plot.right) / 2 - 70, plot.bottom + 45);
  ctx.save();
  ctx.translate(plot.right + 55, (plot.top + plot.bottom) / 2 + 40);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Specific Humidity (g/kg)", 0, 0);
  ctx.restore();
}

function desenharCurvaSaturacao(ctx: CanvasRenderingContext2D): void {
  const traco = construirTraco((t) => {
    const sat = urParaW(100, t) * 1000;
    return sat <= chartConfig.wMax ? sat : null;
  });
  desenharPolilinha(ctx, traco, CORES.saturacao, 2.2);
}

function desenharIsolinhasUmidadeRelativa(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.relativeHumidity) {
    return;
  }
  for (let ur = 10; ur <= 90; ur += 10) {
    const traco = construirTraco((t) => recortarNaSaturacao(urParaW(ur, t) * 1000, t));
    desenharPolilinha(ctx, traco, CORES.umidadeRelativa, 1.1);

    const rotulo = pontoEmFracao(traco, 0.92);
    if (rotulo) {
      ctx.fillStyle = CORES.rotuloUmidadeRelativa;
      ctx.font = "12px Segoe UI";
      ctx.fillText(`${ur}%`, rotulo.x - 4, rotulo.y - 4);
    }
  }
}

function desenharIsolinhasEntalpia(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.enthalpy) {
    return;
  }
  for (let h = 10; h <= 120; h += 2) {
    const traco = construirTraco((t) => recortarNaSaturacao(entalpiaParaW(h, t) * 1000, t));
    // Múltiplos de 10 ganham traço mais forte e rótulo, como referência de leitura.
    const destaque = h % 10 === 0;
    ctx.setLineDash(destaque ? [7, 4] : [3, 4]);
    desenharPolilinha(ctx, traco, CORES.entalpia, destaque ? 1.2 : 0.8);
    ctx.setLineDash([]);

    if (destaque) {
      const rotulo = primeiroPonto(traco);
      if (rotulo) {
        ctx.fillStyle = CORES.rotuloTick;
        ctx.font = "11px Segoe UI";
        ctx.fillText(String(h), rotulo.x - 16, rotulo.y + 2);
      }
    }
  }

  ctx.save();
  ctx.translate(tbsToX(19), wToY(20));
  ctx.rotate(-0.62);
  ctx.fillStyle = CORES.eixo;
  ctx.font = "15px Segoe UI";
  ctx.fillText("Enthalpy (kJ/kg)", 0, 0);
  ctx.restore();
}

function desenharIsolinhasBulboUmido(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.wetBulb) {
    return;
  }
  for (let tbu = 0; tbu <= 30; tbu += 2) {
    // A isolinha de TBU é a isentálpica que passa pelo ar saturado naquela temperatura.
    const hSaturacao = calcularEntalpia(tbu, urParaW(100, tbu));
    const traco = construirTraco((t) => {
      if (t < tbu) {
        return null;
      }
      return recortarNaSaturacao(entalpiaParaW(hSaturacao, t) * 1000, t);
    });
    desenharPolilinha(ctx, traco, CORES.bulboUmido, 0.9);
  }
}

function desenharIsolinhasPressaoVapor(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.vaporPressure) {
    return;
  }
  const plot = getPlotBounds();
  // Pressão de vapor depende só de W, então as isolinhas são horizontais.
  for (let kPa = 0.2; kPa <= 3.2; kPa += 0.2) {
    const wGkg = wDePressaoVapor(kPa * 1000) * 1000;
    if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax) {
      continue;
    }
    const y = wToY(wGkg);
    ctx.beginPath();
    ctx.strokeStyle = CORES.pressaoVapor;
    ctx.lineWidth = 0.8;
    ctx.setLineDash([2, 6]);
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function desenharIsolinhasVolumeEspecifico(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.specificVolume) {
    return;
  }
  for (let v = 0.78; v <= 0.98; v += 0.01) {
    const traco = construirTraco((t) => recortarNaSaturacao(wDeVolumeEspecifico(v, t) * 1000, t));
    desenharPolilinha(ctx, traco, CORES.volumeEspecifico, 0.9);
  }
}

function desenharVetorProcesso(ctx: CanvasRenderingContext2D, points: ProcessPoint[]): void {
  if (points.length < 2) {
    return;
  }
  ctx.beginPath();
  ctx.strokeStyle = CORES.vetorProcesso;
  ctx.lineWidth = 2.2;
  points.forEach((ponto, indice) => {
    const x = tbsToX(ponto.tbs);
    const y = wToY(ponto.wKgKg * 1000);
    if (indice === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
}

/** Deslocamentos manuais dos rótulos, para nenhum cair sobre o vetor do processo. */
const DESLOCAMENTO_ROTULO: Record<string, { dx: number; dy: number }> = {
  P1: { dx: 10, dy: -12 },
  P2: { dx: -22, dy: -8 },
  P3: { dx: -10, dy: -14 },
  P4: { dx: 10, dy: -8 },
};

function desenharPontosProcesso(ctx: CanvasRenderingContext2D, points: ProcessPoint[]): void {
  for (const ponto of points) {
    const x = tbsToX(ponto.tbs);
    const y = wToY(ponto.wKgKg * 1000);

    ctx.beginPath();
    ctx.fillStyle = CORES.pontoProcesso;
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();

    const deslocamento = DESLOCAMENTO_ROTULO[ponto.nome] ?? { dx: 8, dy: -8 };
    ctx.fillStyle = CORES.rotuloEixo;
    ctx.font = "bold 12px Segoe UI";
    ctx.fillText(ponto.nome, x + deslocamento.dx, y + deslocamento.dy);
  }
}

function desenharCursor(ctx: CanvasRenderingContext2D, probe: ProbeState): void {
  const x = tbsToX(probe.tbs);
  const y = wToY(probe.wKgKg * 1000);
  const plot = getPlotBounds();

  ctx.save();
  ctx.strokeStyle = CORES.cursor;
  ctx.lineWidth = 1.2;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(x, plot.top);
  ctx.lineTo(x, plot.bottom);
  ctx.moveTo(plot.left, y);
  ctx.lineTo(plot.right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.lineWidth = 1.8;
  ctx.moveTo(x - 12, y);
  ctx.lineTo(x + 12, y);
  ctx.moveTo(x, y - 12);
  ctx.lineTo(x, y + 12);
  ctx.stroke();
  ctx.restore();
}

/**
 * Corta a curva na interseção com a curva de saturação e nos limites da carta —
 * o item de clipping do checklist da §7. Fora desses limites o traço quebra.
 */
function recortarNaSaturacao(wGkg: number, tbs: number): number | null {
  if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax) {
    return null;
  }
  return wGkg > urParaW(100, tbs) * 1000 ? null : wGkg;
}

/** Amostra uma curva W(TBS) ao longo do eixo, inserindo quebras onde ela sai da carta. */
function construirTraco(resolver: (tbs: number) => number | null): Traco {
  const traco: Traco = [];
  for (let t = chartConfig.tbsMin; t <= chartConfig.tbsMax; t += PASSO_CURVA) {
    const w = resolver(t);
    if (w == null || Number.isNaN(w)) {
      if (traco.length > 0 && traco[traco.length - 1] !== null) {
        traco.push(null);
      }
      continue;
    }
    traco.push({ x: tbsToX(t), y: wToY(w) });
  }
  return traco;
}

function desenharPolilinha(
  ctx: CanvasRenderingContext2D,
  traco: Traco,
  cor: string,
  espessura: number,
): void {
  ctx.beginPath();
  ctx.strokeStyle = cor;
  ctx.lineWidth = espessura;
  let desenhando = false;
  for (const ponto of traco) {
    if (!ponto) {
      desenhando = false;
      continue;
    }
    if (desenhando) {
      ctx.lineTo(ponto.x, ponto.y);
    } else {
      ctx.moveTo(ponto.x, ponto.y);
      desenhando = true;
    }
  }
  ctx.stroke();
}

function primeiroPonto(traco: Traco): Ponto | null {
  return traco.find((ponto): ponto is Ponto => ponto !== null) ?? null;
}

function pontoEmFracao(traco: Traco, fracao: number): Ponto | null {
  return traco[Math.floor(traco.length * fracao)] ?? null;
}
