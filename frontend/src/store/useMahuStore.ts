import { create } from "zustand";

import { describeError } from "@/lib/http";
import {
  calcularProcessoMahu,
  lerMahuMonitor,
  registrarDescarteLeitura,
} from "@/services/psicrometriaApi";
import { useHistoricoStore } from "@/store/useHistoricoStore";
import { useProcessoStore } from "@/store/useProcessoStore";
import type {
  MahuCamposInput,
  MahuLeituraResponse,
  MahuMotivoDescarte,
} from "@/types/api";

const STATUS_INICIAL = "Fotografe o monitor para atualizar os pontos automaticamente.";

/** Sem estes a leitura não pode ser aplicada — são eles que definem o ar de entrada. */
const CHAVES_OBRIGATORIAS = [
  "mt_01",
  "tt01",
  "tt04",
  "tt06",
  "mt07",
  "tt07",
] as const satisfies readonly (keyof MahuCamposInput)[];

/**
 * Conferidos e enviados, mas não exigidos. O bloco SP/PV/MV do painel tem 17 px entre
 * linhas e nem toda foto o resolve; bloquear a leitura por causa dele desperdiçaria os seis
 * campos que saíram bem. Quando vêm, viram desvio e entram no corpus como qualquer outro.
 *
 * `tt02` e `mt_tt_mahu_21` entram aqui pelo mesmo motivo, e por mais um: as ROIs deles ainda
 * são estimadas (ver `perfil_ocr.ROIS_PADRAO`). Enquanto não forem medidas contra o corpus,
 * exigi-los transformaria um recorte mal posicionado em leitura bloqueada.
 */
const CHAVES_OPCIONAIS = [
  "umd_abs_pv",
  "tt04_entalpia_pv",
  "tt04_entalpia_sp",
  "mt_tt_mahu_21",
  "tt02",
] as const satisfies readonly (keyof MahuCamposInput)[];

function montarCampos(
  valores: Record<string, number>,
  leituraId: number | null,
  msNaConferencia: number,
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
    ...Object.fromEntries(
      CHAVES_OPCIONAIS.filter((chave) => Number.isFinite(valores[chave])).map((chave) => [
        chave,
        valores[chave],
      ]),
    ),
    leitura_id: leituraId,
    ms_na_conferencia: msNaConferencia,
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
  /**
   * Quando a conferência abriu, em epoch ms. O tempo até aplicar é o que distingue
   * conferir de carimbar: aplicar em um segundo e meio sem corrigir nada não é evidência
   * de que a leitura estava certa, e no corpus não pode valer como se fosse.
   */
  abertaEm: number;

  setStatus: (status: string) => void;
  descartarLeitura: (motivo: MahuMotivoDescarte | null) => void;
  lerImagem: (file: File) => Promise<void>;
  /**
   * Devolve a mensagem de falha, ou `null` se aplicou.
   *
   * O resultado volta a quem chamou em vez de morrer só no `status`: o `status` é desenhado
   * no TOPO do painel e o botão fica no fim de um formulário de onze campos, que no celular
   * não cabe na tela. Uma falha anunciada lá em cima, fora do campo de visão de quem acabou
   * de tocar no botão, é indistinguível de um botão que não faz nada.
   */
  aplicarConferencia: (valores: Record<string, number>) => Promise<string | null>;
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
  abertaEm: 0,

  setStatus: (status) => set({ status }),

  descartarLeitura: (motivo) => {
    const { leitura, abertaEm } = get();
    // A leitura descartada some da tela na hora; avisar o servidor é assíncrono e não pode
    // atrasar isso. Antes esse evento morria aqui, e a foto ruim ficava marcada como
    // pendente para sempre — indistinguível de quem fechou a aba no meio.
    set({ leitura: null, status: STATUS_INICIAL });
    if (leitura?.id != null) {
      void registrarDescarteLeitura(leitura.id, motivo, Date.now() - abertaEm);
    }
  },

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
      set({
        leitura,
        leituraId: Date.now(),
        abertaEm: Date.now(),
        status: descreverLeitura(leitura),
      });
    } catch (error) {
      set({ status: `Falha na leitura MAHU: ${describeError(error)}` });
    } finally {
      window.clearInterval(cronometro);
      set({ lendo: false, fase: "ocioso" });
    }
  },

  aplicarConferencia: async (valores) => {
    const campos = montarCampos(
      valores,
      get().leitura?.id ?? null,
      Date.now() - get().abertaEm,
    );
    if (!campos) {
      const falha = "Preencha todos os campos obrigatórios com valores numéricos.";
      set({ status: falha });
      return falha;
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
      return null;
    } catch (error) {
      const falha = `Falha ao aplicar a leitura: ${describeError(error)}`;
      set({ status: falha });
      return falha;
    } finally {
      set({ aplicando: false });
    }
  },
}));
