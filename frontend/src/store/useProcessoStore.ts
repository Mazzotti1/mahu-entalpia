import { create } from "zustand";

import { describeError } from "@/lib/http";
import {
  buscarSetpoints,
  calcularProcesso,
  calcularProcessoOtimizado,
  salvarSetpoints,
} from "@/services/psicrometriaApi";
import { useChartStore, useChartStoreOtimizada } from "@/store/useChartStore";
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
  entalpia_alvo_seco: 28.0,
  vazao_m3h: 36575.0,
  pressao_atm: 101325.0,
  preco_kwh: 0.75,
  cop_refrigeracao: 3.5,
  rendimento_aquecimento: 0.95,
  preco_agua_m3: 12.0,
};

interface ProcessoState {
  /** A CARTA CALCULADA: a cadeia que os setpoints impõem. */
  processo: ProcessoResponse | null;
  /**
   * A CARTA ATUAL: a mesma leitura montada só com os instrumentos do painel. `null` quando
   * a origem não foi uma leitura de painel (entrada manual, histórico) — aí a Carta Atual
   * cai de volta na calculada, para a tela não ficar com um lado vazio.
   */
  processoMedido: ProcessoResponse | null;
  /**
   * A CARTA OTIMIZADA: a rota mais barata a partir dos dois primeiros pontos medidos. Vem
   * junto da leitura (`processo.otimizado`); na entrada manual, de `/processo/otimizado`.
   */
  processoOtimizado: ProcessoResponse | null;
  setpoints: Setpoints;
  carregandoSetpoints: boolean;
  salvandoSetpoints: boolean;
  calculando: boolean;
  erro: string | null;
  /** Em qual das 4 regiões da estratégia otimizada o P1 atual cai. `null` até calcular. */
  regiaoOtimizada: number | null;
  /**
   * PID TT04 ENTALPIA (SP) digitado individualmente, um por carta.
   *
   * O da CALCULADA é simulação: entra na requisição e move a cadeia inteira daquela carta,
   * sem gravar nada em `/setpoints` — a configuração da planta continua sendo a de lá.
   *
   * O da ATUAL é o SP que a planta está de fato perseguindo: acompanha a leitura até o
   * backend e volta como desvio contra a entalpia calculada. Não move a Carta Atual, porque
   * nela nenhum ponto vem de setpoint — todos vêm de instrumento.
   */
  entalpiaSpAtual: number | null;
  entalpiaSpOtimizada: number | null;

  carregarSetpoints: () => Promise<void>;
  atualizarSetpoints: (setpoints: Setpoints) => Promise<void>;
  aplicarProcesso: (processo: ProcessoResponse) => void;
  calcularDeEntrada: (tbs: number, ur: number) => Promise<void>;
  definirEntalpiaSpAtual: (valor: number | null) => void;
  definirEntalpiaSpOtimizada: (valor: number | null) => Promise<void>;
  limpar: () => void;
}

export const useProcessoStore = create<ProcessoState>((set, get) => ({
  processo: null,
  processoMedido: null,
  processoOtimizado: null,
  setpoints: SETPOINTS_INICIAIS,
  carregandoSetpoints: false,
  salvandoSetpoints: false,
  calculando: false,
  erro: null,
  regiaoOtimizada: null,
  entalpiaSpAtual: null,
  entalpiaSpOtimizada: null,

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
    // A CARTA ATUAL prefere a cadeia medida. Sem ela — entrada manual, histórico anterior à
    // divisão das cartas — cai na calculada: um lado vazio da tela seria pior que dois lados
    // mostrando a mesma coisa, e a tabela de propriedades ficaria sem nenhum ponto.
    const medido = processo.medido ?? null;
    set({
      processo,
      processoMedido: medido,
      setpoints: processo.setpoints,
      // O SP que veio na leitura: o backend o devolve como desvio, e é de lá que a caixa da
      // Carta Atual se preenche sozinha depois de aplicar uma foto.
      entalpiaSpAtual:
        processo.desvios.find((desvio) => desvio.campo === "tt04_entalpia_sp")?.medido ??
        get().entalpiaSpAtual,
      erro: null,
    });
    useChartStore.getState().aplicarPontosDoProcesso(medido ?? processo);

    // A CARTA OTIMIZADA vem embutida na resposta sempre que houve leitura de painel: ela
    // parte dos dois primeiros pontos MEDIDOS, então só o backend que montou a cadeia medida
    // tem o que ela precisa. Uma segunda requisição partiria de P1 sozinho e produziria uma
    // carta diferente da que a comparação de baixo está somando.
    if (processo.otimizado) {
      set({ processoOtimizado: processo.otimizado });
      useChartStoreOtimizada.getState().aplicarPontosDoProcesso(processo.otimizado);
      return;
    }

    // Sem leitura por trás (entrada manual, histórico) não há TT_02, e a otimização começa
    // na própria entrada. Calculada à parte: se falhar, a Carta Atual — que já teve sucesso
    // — não pode ficar presa esperando por ela.
    const p1 = processo.pontos.find((ponto) => ponto.label === "P1");
    if (p1) {
      calcularProcessoOtimizado({
        tbs: p1.tbs,
        ur: p1.ur,
        entalpia_alvo: get().entalpiaSpOtimizada,
      })
        .then((otimizado) => {
          set({ processoOtimizado: otimizado, regiaoOtimizada: otimizado.regiao });
          useChartStoreOtimizada.getState().aplicarPontosDoProcesso(otimizado);
        })
        .catch(() => {
          // A Carta Otimizada é um comparativo a mais; falhar aqui não pode derrubar a
          // Carta Atual, que já está no ar.
        });
    }
  },

  definirEntalpiaSpAtual: (valor) => set({ entalpiaSpAtual: valor }),

  /**
   * Redesenha só a Carta Calculada com o alvo informado. Não toca em `/setpoints`: o campo
   * existe para experimentar um alvo, e gravar a configuração da planta a cada tecla
   * mudaria o que os outros celulares estão vendo.
   */
  definirEntalpiaSpOtimizada: async (valor) => {
    set({ entalpiaSpOtimizada: valor });
    const p1 = get().processo?.pontos.find((ponto) => ponto.label === "P1");
    if (!p1) {
      return;
    }
    try {
      const otimizado = await calcularProcessoOtimizado({
        tbs: p1.tbs,
        ur: p1.ur,
        entalpia_alvo: valor,
      });
      useChartStoreOtimizada.getState().aplicarPontosDoProcesso(otimizado);
      set({ processoOtimizado: otimizado, regiaoOtimizada: otimizado.regiao });
    } catch (error) {
      set({ erro: describeError(error) });
    }
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

  limpar: () => set({ processo: null, processoMedido: null, erro: null }),
}));
