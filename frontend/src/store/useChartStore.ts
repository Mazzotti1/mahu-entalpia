import { create } from "zustand";

import { DEFAULT_LAYER_VISIBILITY, type LayerKey, type LayerVisibility } from "@/chart/layers";
import type { ProcessoResponse, SimulacaoResponse } from "@/types/api";
import type { ProbeState, ProcessPoint, ProcessSegment } from "@/types/chart";

function toProcessPoint(ponto: SimulacaoResponse["pontos"][number]): ProcessPoint {
  return {
    id: ponto.id,
    nome: ponto.label,
    tbs: ponto.tbs,
    // A API responde em g/kg; as fórmulas do desenho trabalham em kg/kg.
    wKgKg: ponto.w / 1000,
    ur: ponto.ur,
    entalpia: ponto.entalpia,
    tbu: ponto.tbu,
    volumeEspecifico: ponto.volume_especifico,
    pontoOrvalho: ponto.ponto_orvalho,
    fonteCalculo: ponto.fonte_calculo,
    // Simulação avulsa (histórico anterior ao processo encadeado): o ponto foi digitado à
    // mão, seja qual for a fonte de cálculo interna (ur/entalpia/w_abs).
    fonte: "lido_digitado",
  };
}

function paraSegmentos(processo: ProcessoResponse): ProcessSegment[] {
  const porLabel = new Map(processo.pontos.map((ponto) => [ponto.label, ponto]));
  return processo.etapas.flatMap((etapa) => {
    const inicio = porLabel.get(etapa.de);
    const fim = porLabel.get(etapa.para);
    // Etapa nula não tem trajetória: os dois pontos coincidem.
    if (!inicio || !fim || !etapa.ativa) {
      return [];
    }
    return [
      {
        tipo: etapa.tipo,
        de: etapa.de,
        para: etapa.para,
        inicio: { tbs: inicio.tbs, wGkg: inicio.w },
        fim: { tbs: fim.tbs, wGkg: fim.w },
        joelho: etapa.joelho ? { tbs: etapa.joelho.tbs, wGkg: etapa.joelho.w } : null,
      },
    ];
  });
}

interface ChartState {
  layers: LayerVisibility;
  points: ProcessPoint[];
  /** Vazio quando os pontos não vieram de um processo (histórico antigo). */
  segments: ProcessSegment[];
  probe: ProbeState | null;
  carregando: boolean;
  erro: string | null;

  toggleLayer: (key: LayerKey) => void;
  setProbe: (probe: ProbeState) => void;
  resetProbe: () => void;
  /** Pontos avulsos, sem trajetórias: histórico anterior à migração 3. */
  aplicarSimulacao: (simulacao: SimulacaoResponse) => void;
  aplicarPontosDoProcesso: (processo: ProcessoResponse) => void;
}

export const useChartStore = create<ChartState>((set, get) => ({
  layers: DEFAULT_LAYER_VISIBILITY,
  points: [],
  segments: [],
  probe: null,
  carregando: false,
  erro: null,

  toggleLayer: (key) =>
    set((state) => ({ layers: { ...state.layers, [key]: !state.layers[key] } })),

  setProbe: (probe) => set({ probe }),

  /** Com o ponteiro fora da carta, o indicador volta a mostrar o primeiro ponto. */
  resetProbe: () => {
    const primeiro = get().points[0];
    set({ probe: primeiro ? { tbs: primeiro.tbs, wKgKg: primeiro.wKgKg } : null });
  },

  aplicarSimulacao: (simulacao) => {
    if (simulacao.pontos.length === 0) {
      set({ erro: "A API retornou uma simulação sem pontos." });
      return;
    }
    const points = simulacao.pontos.map(toProcessPoint);
    set({
      points,
      // Uma simulação avulsa não descreve trajetórias: os pontos são ligados por reta.
      segments: [],
      probe: { tbs: points[0].tbs, wKgKg: points[0].wKgKg },
      erro: null,
    });
  },

  aplicarPontosDoProcesso: (processo) => {
    const points: ProcessPoint[] = processo.pontos.map((ponto) => ({
      id: null,
      nome: ponto.label,
      tbs: ponto.tbs,
      wKgKg: ponto.w / 1000,
      ur: ponto.ur,
      entalpia: ponto.entalpia,
      tbu: ponto.tbu,
      volumeEspecifico: ponto.volume_especifico,
      pontoOrvalho: ponto.ponto_orvalho,
      fonteCalculo: "w_abs",
      fonte: ponto.fonte,
      saturado: ponto.saturado,
    }));
    set({
      points,
      segments: paraSegmentos(processo),
      probe: { tbs: points[0].tbs, wKgKg: points[0].wKgKg },
      erro: null,
    });
  },

}));
