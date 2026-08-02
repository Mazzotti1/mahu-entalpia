import { create } from "zustand";

import { describeError, streamUrl } from "@/lib/http";
import {
  buscarProcessoDaSimulacao,
  buscarSimulacao,
  listarSimulacoes,
} from "@/services/psicrometriaApi";
import { useProcessoStore } from "@/store/useProcessoStore";
import { useChartStore } from "@/store/useChartStore";
import type { SimulacaoResumo } from "@/types/api";

/**
 * Sondagem usada só quando o SSE não vinga — proxy que não deixa passar `text/event-stream`,
 * rede corporativa, navegador sem EventSource. Nesse caso 4 s é rápido o bastante para uma
 * leitura que acontece a cada vários minutos.
 */
const INTERVALO_POLL_MS = 4000;
const TAMANHO_PAGINA = 30;

interface HistoricoState {
  itens: SimulacaoResumo[];
  total: number;
  selecionadaId: number | null;
  /**
   * Enquanto true, a chegada de uma leitura nova troca a carta automaticamente — é o que
   * faz o PC espelhar o celular. Escolher uma leitura antiga desliga; voltar para a mais
   * recente religa.
   */
  seguindoUltima: boolean;
  carregando: boolean;
  erro: string | null;
  /** Evita que o StrictMode do React semeie duas simulações na montagem. */
  bootstrapIniciado: boolean;
  /** "sse" enquanto o stream está de pé; "polling" depois que ele desiste. */
  transporte: "conectando" | "sse" | "polling";

  bootstrap: () => Promise<void>;
  atualizarLista: () => Promise<void>;
  selecionar: (id: number) => Promise<void>;
  voltarASeguir: () => Promise<void>;
  registrarLeituraLocal: (id: number) => void;
  aplicarResumoRecebido: (resumo: SimulacaoResumo) => void;
  /** Abre o stream (ou o polling de reserva) e devolve a função de limpeza. */
  observarLeituras: () => () => void;
}

export const useHistoricoStore = create<HistoricoState>((set, get) => ({
  itens: [],
  total: 0,
  selecionadaId: null,
  seguindoUltima: true,
  carregando: false,
  erro: null,
  bootstrapIniciado: false,
  transporte: "conectando",

  /**
   * Na carga da página, adota a leitura mais recente que já existir. Só quando o histórico
   * está vazio é que a simulação de exemplo é criada — antes disso cada refresh gravava uma
   * simulação nova, o que com o histórico visível viraria lixo acumulando na lista.
   */
  bootstrap: async () => {
    if (get().bootstrapIniciado) {
      return;
    }
    set({ bootstrapIniciado: true });

    await get().atualizarLista();
    if (get().itens.length > 0) {
      return;
    }
    try {
      // Semeia um processo, e não uma simulação avulsa: assim a primeira tela já traz
      // etapas, kW e trajetórias, e não quatro pontos ligados por reta.
      await useProcessoStore.getState().calcularDeEntrada(20.27, 64.09);
      const simulacaoId = useProcessoStore.getState().processo?.simulacao_id;
      if (simulacaoId != null) {
        get().registrarLeituraLocal(simulacaoId);
      }
    } catch {
      // O erro já está em useProcessoStore.erro; o indicador o exibe.
    }
  },

  atualizarLista: async () => {
    try {
      const { itens, total } = await listarSimulacoes(TAMANHO_PAGINA);
      const maisRecente = itens[0];
      set({ itens, total, erro: null });

      // Chegou leitura nova (do celular, por exemplo) e estamos acompanhando: adota.
      if (maisRecente && get().seguindoUltima && maisRecente.id !== get().selecionadaId) {
        await get().selecionar(maisRecente.id);
        set({ seguindoUltima: true });
      }
    } catch (error) {
      set({ erro: describeError(error) });
    }
  },

  selecionar: async (id) => {
    if (get().carregando) {
      return;
    }
    set({ carregando: true });
    try {
      // Entrada gravada com o processo traz etapas e kW; as anteriores à migração 3 não
      // têm processo nenhum e caem no caminho antigo, com os pontos ligados por reta.
      const processo = await buscarProcessoDaSimulacao(id);
      if (processo) {
        useProcessoStore.getState().aplicarProcesso(processo);
      } else {
        useProcessoStore.getState().limpar();
        useChartStore.getState().aplicarSimulacao(await buscarSimulacao(id));
      }
      // Escolher algo que não é o topo da lista desliga o acompanhamento automático.
      set({ selecionadaId: id, seguindoUltima: get().itens[0]?.id === id, erro: null });
    } catch (error) {
      set({ erro: describeError(error) });
    } finally {
      set({ carregando: false });
    }
  },

  voltarASeguir: async () => {
    set({ seguindoUltima: true });
    const maisRecente = get().itens[0];
    if (maisRecente && maisRecente.id !== get().selecionadaId) {
      await get().selecionar(maisRecente.id);
      set({ seguindoUltima: true });
    }
  },

  /**
   * Chamado logo após este dispositivo criar uma leitura: adota o id na hora, sem esperar
   * o próximo poll, para a carta não piscar de volta para a leitura anterior.
   */
  registrarLeituraLocal: (id) => {
    set({ selecionadaId: id, seguindoUltima: true });
    void get().atualizarLista();
  },

  /** Insere (ou atualiza) um resumo vindo do stream, mantendo a lista ordenada por id. */
  aplicarResumoRecebido: (resumo) => {
    const semDuplicata = get().itens.filter((item) => item.id !== resumo.id);
    const jaExistia = semDuplicata.length !== get().itens.length;
    const itens = [resumo, ...semDuplicata]
      .sort((a, b) => b.id - a.id)
      .slice(0, TAMANHO_PAGINA);

    set({
      itens,
      total: jaExistia ? get().total : get().total + 1,
      erro: null,
    });

    if (get().seguindoUltima && itens[0] && itens[0].id !== get().selecionadaId) {
      void get().selecionar(itens[0].id).then(() => set({ seguindoUltima: true }));
    }
  },

  observarLeituras: () => {
    let fonte: EventSource | null = null;
    let timer: number | undefined;

    const pararPolling = () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
        timer = undefined;
      }
    };

    const cairParaPolling = () => {
      if (timer !== undefined) {
        return;
      }
      set({ transporte: "polling" });
      timer = window.setInterval(() => void get().atualizarLista(), INTERVALO_POLL_MS);
    };

    const fechar = () => {
      fonte?.close();
      fonte = null;
    };

    const abrir = () => {
      if (fonte || typeof EventSource === "undefined") {
        if (typeof EventSource === "undefined") {
          cairParaPolling();
        }
        return;
      }

      set({ transporte: "conectando" });
      fonte = new EventSource(streamUrl("/simulacoes/stream"));

      fonte.addEventListener("open", () => {
        pararPolling();
        set({ transporte: "sse" });
        // A conexão pode ter caído por tempo suficiente para o Last-Event-ID não cobrir
        // tudo (o servidor limita o reenvio); ressincronizar a lista é barato e garante.
        void get().atualizarLista();
      });

      fonte.addEventListener("simulacao", (evento) => {
        try {
          get().aplicarResumoRecebido(JSON.parse((evento as MessageEvent<string>).data));
        } catch {
          void get().atualizarLista();
        }
      });

      fonte.addEventListener("error", () => {
        // readyState CONNECTING significa que o EventSource vai tentar de novo sozinho —
        // é o caso comum de rede oscilando. CLOSED é desistência: aí o polling assume.
        if (fonte?.readyState === EventSource.CLOSED) {
          fechar();
          cairParaPolling();
        }
      });
    };

    // Aba escondida não precisa de conexão aberta: poupa bateria no celular. Ao voltar,
    // reabre e ressincroniza.
    const aoMudarVisibilidade = () => {
      if (document.visibilityState === "visible") {
        void get().atualizarLista();
        abrir();
      } else {
        fechar();
        pararPolling();
      }
    };

    if (document.visibilityState === "visible") {
      abrir();
    }
    document.addEventListener("visibilitychange", aoMudarVisibilidade);

    return () => {
      fechar();
      pararPolling();
      document.removeEventListener("visibilitychange", aoMudarVisibilidade);
    };
  },
}));
