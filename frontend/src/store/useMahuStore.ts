import { create } from "zustand";

import { describeError } from "@/lib/http";
import { calcularProcessoMahu, lerMahuMonitor } from "@/services/psicrometriaApi";
import { useHistoricoStore } from "@/store/useHistoricoStore";
import { useProcessoStore } from "@/store/useProcessoStore";
import type { MahuCamposInput, MahuLeituraResponse } from "@/types/api";

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

function montarCampos(
  valores: Record<string, number>,
  leituraId: number | null,
): MahuCamposInput | null {
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
    leitura_id: leituraId,
  };
}

function descreverLeitura(leitura: MahuLeituraResponse): string {
  if (leitura.missing_keys.length > 0) {
    return `Leitura incompleta. Preencha à mão: ${leitura.missing_keys.join(", ")}`;
  }
  if (leitura.avisos.length > 0) {
    // Os campos podem ter saído confiáveis um a um e ainda assim não fechar entre si.
    return "Os valores lidos não são coerentes entre si. Confira antes de aplicar.";
  }
  if (leitura.requires_review) {
    return "Confira os campos destacados antes de aplicar.";
  }
  return "Leitura concluída. Confira os valores e aplique.";
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

export const useMahuStore = create<MahuState>((set, get) => ({
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
      // A conferência é sempre aberta, inclusive quando todos os campos saíram confiáveis.
      // Aplicar direto escondia do usuário o que tinha sido lido, e foi assim que uma
      // leitura com quatro campos corrompidos entrou no banco sem ninguém ver: a confiança
      // por campo estava boa e nada pediu revisão (docs/especificacao-processo-mahu.md §8.4).
      // Como efeito colateral, toda leitura passa a produzir o par sugerido/aplicado, que é
      // o ground truth rotulado de que O5.3 precisa.
      set({ leitura, leituraId: Date.now(), status: descreverLeitura(leitura) });
    } catch (error) {
      set({ status: `Falha na leitura MAHU: ${describeError(error)}` });
    } finally {
      window.clearInterval(cronometro);
      set({ lendo: false, fase: "ocioso" });
    }
  },

  aplicarConferencia: async (valores) => {
    const campos = montarCampos(valores, get().leitura?.id ?? null);
    if (!campos) {
      set({ status: "Preencha todos os campos obrigatórios com valores numéricos." });
      return;
    }

    set({ aplicando: true, status: "Resolvendo o processo a partir dos valores conferidos..." });
    try {
      // TT01 e MT_01 são o ar de entrada; o resto do processo vem dos setpoints, e as
      // demais medições voltam como desvio (decisões B e D).
      const processo = await calcularProcessoMahu(campos);
      useProcessoStore.getState().aplicarProcesso(processo);
      if (processo.simulacao_id != null) {
        useHistoricoStore.getState().registrarLeituraLocal(processo.simulacao_id);
      }
      set({
        leitura: null,
        status:
          `Processo atualizado. Refrigeração ${processo.totais.q_refrigeracao_kw.toFixed(1)} kW, ` +
          `aquecimento ${processo.totais.q_aquecimento_kw.toFixed(1)} kW.`,
      });
    } catch (error) {
      set({ status: `Falha ao aplicar a leitura: ${describeError(error)}` });
    } finally {
      set({ aplicando: false });
    }
  },
}));
