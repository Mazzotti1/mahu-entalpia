import { create } from "zustand";

import { describeError } from "@/lib/http";
import { criarSimulacaoMahu, lerMahuMonitor } from "@/services/psicrometriaApi";
import { useChartStore } from "@/store/useChartStore";
import { useHistoricoStore } from "@/store/useHistoricoStore";
import type { MahuCampoOCR, MahuCamposInput, MahuLeituraResponse } from "@/types/api";

const STATUS_INICIAL = "Fotografe o monitor para atualizar os pontos automaticamente.";

/** Únicos campos que alimentam o cálculo; os demais do painel são só conferência. */
const CHAVES_OBRIGATORIAS = [
  "mt_01",
  "tt01",
  "tt04",
  "tt06",
  "mt07",
  "tt07",
] as const satisfies readonly (keyof MahuCamposInput)[];

function montarCampos(valores: Record<string, number>): MahuCamposInput | null {
  if (CHAVES_OBRIGATORIAS.some((chave) => !Number.isFinite(valores[chave]))) {
    return null;
  }
  return {
    mt_01: valores.mt_01,
    tt01: valores.tt01,
    tt04: valores.tt04,
    tt06: valores.tt06,
    mt07: valores.mt07,
    tt07: valores.tt07,
  };
}

function resumirCampos(campos: MahuCampoOCR[]): string {
  return campos
    .filter((campo) => campo.obrigatorio && campo.pv != null)
    .map((campo) => `${campo.label}: ${campo.pv} ${campo.unidade}`)
    .join(" | ");
}

/**
 * `enviando` tem progresso real (bytes subindo); `processando` não — o OCR acontece numa
 * chamada só e o servidor não reporta fração. Nessa fase o que dá para mostrar de honesto
 * é o tempo decorrido, não uma barra inventada.
 */
export type FaseLeitura = "ocioso" | "enviando" | "processando";

interface MahuState {
  status: string;
  lendo: boolean;
  aplicando: boolean;
  fase: FaseLeitura;
  /** 0..100, válido durante a fase `enviando`. */
  progressoUpload: number;
  segundosDecorridos: number;
  /** Leitura aguardando conferência; `null` quando não há formulário aberto. */
  leitura: MahuLeituraResponse | null;
  /** Muda a cada leitura para o formulário remontar com os novos valores. */
  leituraId: number;

  setStatus: (status: string) => void;
  descartarLeitura: () => void;
  lerImagem: (file: File) => Promise<void>;
  aplicarConferencia: (valores: Record<string, number>) => Promise<void>;
}

export const useMahuStore = create<MahuState>((set) => ({
  status: STATUS_INICIAL,
  lendo: false,
  aplicando: false,
  fase: "ocioso",
  progressoUpload: 0,
  segundosDecorridos: 0,
  leitura: null,
  leituraId: 0,

  setStatus: (status) => set({ status }),

  descartarLeitura: () => set({ leitura: null }),

  lerImagem: async (file) => {
    set({
      lendo: true,
      leitura: null,
      fase: "enviando",
      progressoUpload: 0,
      segundosDecorridos: 0,
      // Foto de celular tem alguns MB e o OCR roda em CPU: sem acompanhamento a espera
      // parece travamento.
      status: "Enviando a foto do MAHU...",
    });

    const inicio = Date.now();
    // 250 ms para o contador de segundos virar sem atraso perceptível.
    const cronometro = window.setInterval(
      () => set({ segundosDecorridos: Math.floor((Date.now() - inicio) / 1000) }),
      250,
    );

    try {
      const leitura = await lerMahuMonitor(file, (porcentagem) => {
        set({
          progressoUpload: porcentagem,
          // Bytes no fim da fila = servidor trabalhando a partir daqui.
          fase: porcentagem >= 100 ? "processando" : "enviando",
          status:
            porcentagem >= 100
              ? "Lendo o painel... isso leva alguns segundos."
              : "Enviando a foto do MAHU...",
        });
      });
      const abrirConferencia = (status: string) =>
        set({ leitura, leituraId: Date.now(), status });

      if (leitura.missing_keys.length > 0) {
        abrirConferencia(`Leitura incompleta. Preencha à mão: ${leitura.missing_keys.join(", ")}`);
        return;
      }
      if (leitura.requires_review || !leitura.suggested_simulacao) {
        abrirConferencia("Leitura concluída com campos duvidosos. Confira os valores e aplique.");
        return;
      }

      // Todos os campos obrigatórios saíram confiáveis: aplica direto.
      const simulacao = await useChartStore
        .getState()
        .carregarSimulacao(leitura.suggested_simulacao);
      useHistoricoStore.getState().registrarLeituraLocal(simulacao.id);
      set({ status: `Leitura aplicada.\n${resumirCampos(leitura.campos)}` });
    } catch (error) {
      set({ status: `Falha na leitura MAHU: ${describeError(error)}` });
    } finally {
      window.clearInterval(cronometro);
      set({ lendo: false, fase: "ocioso" });
    }
  },

  aplicarConferencia: async (valores) => {
    const campos = montarCampos(valores);
    if (!campos) {
      set({ status: "Preencha todos os campos obrigatórios com valores numéricos." });
      return;
    }

    set({ aplicando: true, status: "Calculando pontos a partir dos valores conferidos..." });
    try {
      const simulacao = await criarSimulacaoMahu(campos);
      useChartStore.getState().aplicarSimulacao(simulacao);
      useHistoricoStore.getState().registrarLeituraLocal(simulacao.id);
      set({ leitura: null, status: "Carta atualizada com a leitura conferida do MAHU." });
    } catch (error) {
      set({ status: `Falha ao aplicar a leitura: ${describeError(error)}` });
    } finally {
      set({ aplicando: false });
    }
  },
}));
