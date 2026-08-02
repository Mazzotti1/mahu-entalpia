import { create } from "zustand";

import { describeError } from "@/lib/http";
import {
  buscarSetpoints,
  calcularProcesso,
  salvarSetpoints,
} from "@/services/psicrometriaApi";
import { useChartStore } from "@/store/useChartStore";
import type { ProcessoResponse, Setpoints } from "@/types/api";

/**
 * Espelham os defaults do backend (`models.SetpointsInput`) só para a UI ter o que mostrar
 * antes do primeiro GET responder. Quem manda é o servidor: os setpoints são da planta, e
 * dois celulares abrindo o app precisam ver a mesma configuração.
 */
export const SETPOINTS_INICIAIS: Setpoints = {
  w_saida: 7.3,
  tbs_final: 20.0,
  entalpia_alvo: 36.2,
  vazao_m3h: 36575.0,
  pressao_atm: 101325.0,
};

interface ProcessoState {
  processo: ProcessoResponse | null;
  setpoints: Setpoints;
  carregandoSetpoints: boolean;
  salvandoSetpoints: boolean;
  calculando: boolean;
  erro: string | null;

  carregarSetpoints: () => Promise<void>;
  atualizarSetpoints: (setpoints: Setpoints) => Promise<void>;
  aplicarProcesso: (processo: ProcessoResponse) => void;
  calcularDeEntrada: (tbs: number, ur: number) => Promise<void>;
  limpar: () => void;
}

export const useProcessoStore = create<ProcessoState>((set, get) => ({
  processo: null,
  setpoints: SETPOINTS_INICIAIS,
  carregandoSetpoints: false,
  salvandoSetpoints: false,
  calculando: false,
  erro: null,

  carregarSetpoints: async () => {
    set({ carregandoSetpoints: true });
    try {
      set({ setpoints: await buscarSetpoints(), erro: null });
    } catch (error) {
      set({ erro: describeError(error) });
    } finally {
      set({ carregandoSetpoints: false });
    }
  },

  atualizarSetpoints: async (setpoints) => {
    set({ salvandoSetpoints: true });
    try {
      const gravados = await salvarSetpoints(setpoints);
      set({ setpoints: gravados, erro: null });

      // Mudar setpoint muda o processo inteiro: sem recalcular, a carta e a tabela de kW
      // continuariam mostrando o resultado da configuração anterior.
      const atual = get().processo;
      const p1 = atual?.pontos.find((ponto) => ponto.label === "P1");
      if (p1) {
        await get().calcularDeEntrada(p1.tbs, p1.ur);
      }
    } catch (error) {
      set({ erro: describeError(error) });
      throw error;
    } finally {
      set({ salvandoSetpoints: false });
    }
  },

  aplicarProcesso: (processo) => {
    set({ processo, setpoints: processo.setpoints, erro: null });
    useChartStore.getState().aplicarPontosDoProcesso(processo);
  },

  calcularDeEntrada: async (tbs, ur) => {
    set({ calculando: true });
    try {
      get().aplicarProcesso(await calcularProcesso({ tbs, ur }));
    } catch (error) {
      set({ erro: describeError(error) });
    } finally {
      set({ calculando: false });
    }
  },

  limpar: () => set({ processo: null, erro: null }),
}));
