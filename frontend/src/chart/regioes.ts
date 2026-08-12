/**
 * As 4 regiões da estratégia otimizada (docs anexados ao pedido), só para o fundo colorido
 * da carta otimizada — quem decide o alvo de entalpia de verdade é o backend
 * (`entalpia_alvo_otimizada`, regra mais simples e sem lacunas). Os limiares aqui são os
 * mesmos de `backend/services/processo.py::classificar_regiao`, mantidos em espelho.
 */
import { chartConfig, getPlotBounds, xToTbs, yToW } from "@/chart/config";
import { calcularEntalpia, urParaW } from "@/lib/psicrometria";

export type Regiao = 1 | 2 | 3 | 4 | null;

const W_SAIDA_OTIMIZADO = 7.3;

export function classificarRegiao(tbs: number, wGkg: number, h: number): Regiao {
  if (tbs <= 23 && h < 28) {
    return 1;
  }
  if (tbs >= 9 && tbs <= 27 && wGkg < W_SAIDA_OTIMIZADO && h > 28) {
    return 2;
  }
  if (tbs >= 9 && tbs <= 17 && wGkg > W_SAIDA_OTIMIZADO && h < 36) {
    return 3;
  }
  if (h > 36 && wGkg > W_SAIDA_OTIMIZADO) {
    return 4;
  }
  return null;
}

export const CORES_REGIAO: Record<1 | 2 | 3 | 4, string> = {
  1: "rgba(239, 68, 68, 0.20)",
  2: "rgba(249, 115, 22, 0.20)",
  3: "rgba(16, 185, 129, 0.20)",
  4: "rgba(59, 130, 246, 0.20)",
};

export const ROTULOS_REGIAO: Record<1 | 2 | 3 | 4, string> = {
  1: "Região 1 — aquecer até 28 kJ/kg + umidificar",
  2: "Região 2 — resfriar até 28 kJ/kg + umidificar",
  3: "Região 3 — aquecer até 36 kJ/kg + umidificar/desumidificar",
  4: "Região 4 — resfriar até 36 kJ/kg + umidificar/desumidificar",
};

/** Tamanho do bloco de varredura, em pixels lógicos da carta (espaço 1200×760). */
const TAMANHO_BLOCO = 3;

let fundoCache: HTMLCanvasElement | null = null;

/**
 * As regiões dependem só dos limites fixos da carta (tbs/w/h), nunca de P1, pontos ou
 * cursor — por isso valem a pena cachear num canvas à parte em vez de recalcular a cada
 * quadro. `renderChart` roda a cada movimento do mouse sobre a carta; sem cache, a
 * varredura de ~100 mil blocos rodaria a cada um desses movimentos.
 */
function construirFundoRegioes(): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = chartConfig.width;
  canvas.height = chartConfig.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return canvas;
  }
  const plot = getPlotBounds();

  for (let y = plot.top; y < plot.bottom; y += TAMANHO_BLOCO) {
    const wGkg = yToW(y + TAMANHO_BLOCO / 2);
    for (let x = plot.left; x < plot.right; x += TAMANHO_BLOCO) {
      const tbs = xToTbs(x + TAMANHO_BLOCO / 2);
      // Só existe ar de verdade até a curva de saturação.
      if (wGkg > urParaW(100, tbs) * 1000) {
        continue;
      }
      const regiao = classificarRegiao(tbs, wGkg, calcularEntalpia(tbs, wGkg / 1000));
      if (regiao === null) {
        continue;
      }
      ctx.fillStyle = CORES_REGIAO[regiao];
      ctx.fillRect(x, y, TAMANHO_BLOCO, TAMANHO_BLOCO);
    }
  }
  return canvas;
}

export function desenharFundoRegioes(ctx: CanvasRenderingContext2D): void {
  if (!fundoCache) {
    fundoCache = construirFundoRegioes();
  }
  ctx.drawImage(fundoCache, 0, 0);
}
