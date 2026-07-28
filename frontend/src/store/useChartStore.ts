import { create } from "zustand";

import { DEFAULT_LAYER_VISIBILITY, type LayerKey, type LayerVisibility } from "@/chart/layers";
import { describeError } from "@/lib/http";
import { enviarSimulacao } from "@/services/psicrometriaApi";
import type { SimulacaoInput, SimulacaoResponse } from "@/types/api";
import type { ProbeState, ProcessPoint } from "@/types/chart";

/**
 * Mesmos valores do monitor em `docs/fotosMahu/6.jpg`, com o mapeamento de
 * `backend/services/mahu.py`: assim a carta inicial e a vinda da câmera coincidem.
 * P2 vem de TT_04 saturado — a entrada do doc §6 (TBS 12,20 + h 36,20) exigiria
 * W = 9,48 g/kg contra W_sat = 8,85 g/kg, ou seja UR de 107%, e é rejeitada pela API.
 */
const SIMULACAO_PADRAO: SimulacaoInput = {
  nome: "Simulação Padrão ASHRAE",
  descricao: "Pontos de processo da carta psicrométrica",
  pontos: [
    { label: "P1", tbs: 20.27, ur: 63.89 },
    { label: "P2", tbs: 12.2, ur: 100.0 },
    { label: "P3", tbs: 8.7, ur: 100.0 },
    { label: "P4", tbs: 21.2, ur: 46.48 },
  ],
};

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
  };
}

interface ChartState {
  layers: LayerVisibility;
  points: ProcessPoint[];
  probe: ProbeState | null;
  carregando: boolean;
  erro: string | null;

  toggleLayer: (key: LayerKey) => void;
  setProbe: (probe: ProbeState) => void;
  resetProbe: () => void;
  aplicarSimulacao: (simulacao: SimulacaoResponse) => void;
  carregarSimulacao: (payload: SimulacaoInput) => Promise<SimulacaoResponse>;
  /** Cria a simulação de exemplo. Só faz sentido com o histórico vazio. */
  semearSimulacaoPadrao: () => Promise<SimulacaoResponse>;
}

export const useChartStore = create<ChartState>((set, get) => ({
  layers: DEFAULT_LAYER_VISIBILITY,
  points: [],
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
      probe: { tbs: points[0].tbs, wKgKg: points[0].wKgKg },
      erro: null,
    });
  },

  carregarSimulacao: async (payload) => {
    set({ carregando: true });
    try {
      const simulacao = await enviarSimulacao(payload);
      get().aplicarSimulacao(simulacao);
      return simulacao;
    } catch (error) {
      set({ erro: describeError(error) });
      throw error;
    } finally {
      set({ carregando: false });
    }
  },

  semearSimulacaoPadrao: () => get().carregarSimulacao(SIMULACAO_PADRAO),
}));
