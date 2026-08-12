/** Espelho dos modelos Pydantic de `backend/models.py`. */

export interface LoginInput {
  username: string;
  senha: string;
}

/** Quem está autenticado. Não há token aqui: a sessão vive em cookies HttpOnly. */
export interface Usuario {
  id: number;
  username: string;
  papel: string;
}

export type FonteCalculo = "ur" | "entalpia" | "w_abs" | "banco";

/**
 * O backend exige exatamente uma fonte de entrada entre `ur`, `entalpia` e `w_abs`
 * (validador `PontoInput.validate_input_source`); mandar duas devolve 422.
 */
export interface PontoInput {
  label: string;
  tbs: number;
  ur?: number | null;
  entalpia?: number | null;
  w_abs?: number | null;
  pressao_atm?: number;
}

export interface PontoResponse {
  id: number | null;
  label: string;
  /** Temperatura de bulbo seco (°C) */
  tbs: number;
  /** Umidade absoluta (g/kg) */
  w: number;
  /** Umidade relativa (%) */
  ur: number;
  /** Entalpia (kJ/kg) */
  entalpia: number;
  /** Temperatura de bulbo úmido (°C) */
  tbu: number;
  /** Volume específico (m³/kg) */
  volume_especifico: number;
  /** Temperatura de ponto de orvalho (°C) */
  ponto_orvalho: number;
  fonte_calculo: FonteCalculo;
}

export interface SimulacaoInput {
  nome: string;
  descricao?: string | null;
  pontos: PontoInput[];
}

export interface SimulacaoResponse {
  id: number;
  nome: string;
  pontos: PontoResponse[];
}

/** Entrada do histórico: identifica a leitura sem carregar os pontos. */
export interface SimulacaoResumo {
  id: number;
  nome: string;
  /** ISO 8601 em UTC (com sufixo Z). */
  criado_em: string;
  total_pontos: number;
  p1_tbs: number | null;
  p1_ur: number | null;
}

export interface SimulacaoListaResponse {
  total: number;
  itens: SimulacaoResumo[];
}

/**
 * - `ok`: variantes concordaram, confiança suficiente e valor na faixa de operação
 * - `low_confidence`: valor fisicamente plausível, mas duvidoso (pouca concordância,
 *   confiança baixa, ou fora da faixa de operação do campo)
 * - `unreadable`: nada legível ou fora da faixa física do campo
 */
export type MahuCampoStatus = "ok" | "low_confidence" | "unreadable";

export interface MahuCampoOCR {
  key: string;
  label: string;
  unidade: string;
  obrigatorio: boolean;
  raw_text: string | null;
  pv: number | null;
  confidence: number | null;
  roi: number[];
  status: MahuCampoStatus;
  /** Por que o status não é `ok`, em texto exibível. `null` quando a leitura passou. */
  motivo: string | null;
}

// --- Processo -------------------------------------------------------------------------

/** O que a planta persegue. Decisão B: os alvos vêm daqui, não das medições. */
export interface Setpoints {
  /** Umidade absoluta de saída, g/kg. */
  w_saida: number;
  /** Temperatura de insuflamento, °C. */
  tbs_final: number;
  /** Entalpia alvo de P2, kJ/kg. */
  entalpia_alvo: number;
  /** Entalpia alvo de P2 na carta otimizada quando P1 chega mais seco que w_saida, kJ/kg. */
  entalpia_alvo_seco: number;
  /** Vazão volumétrica medida na ENTRADA (decisão A), m³/h. */
  vazao_m3h: number;
  /** Pressão atmosférica em Pa — não em kPa. */
  pressao_atm: number;
}

/**
 * P1 vem de TT01+MT_01, lidos/digitados no painel. P2..P5 são a cadeia calculada a partir
 * dos setpoints (decisão B) — "calculado" mesmo quando um campo do painel existe para
 * conferir o mesmo estado; essa conferência é o que está em `ProcessoResponse.desvios`.
 */
export type FontePonto = "lido_digitado" | "calculado";

export interface PontoProcesso {
  label: string;
  tbs: number;
  /** g/kg */
  w: number;
  ur: number;
  entalpia: number;
  tbu: number;
  volume_especifico: number;
  ponto_orvalho: number;
  saturado: boolean;
  fonte: FontePonto;
}

/**
 * `tipo` decide a trajetória desenhada na carta e em qual serpentina o kW é lançado.
 * `joelho` marca onde o percurso dobrou sobre a curva de saturação; `null` quando o
 * trecho é uma reta só.
 */
export type TipoEtapa =
  | "resfriamento_sensivel"
  | "resfriamento_desumidificacao"
  | "aquecimento_sensivel"
  | "umidificacao_adiabatica"
  | "nula";

export interface EtapaProcesso {
  tipo: TipoEtapa;
  de: string;
  para: string;
  ativa: boolean;
  delta_h: number;
  delta_w: number;
  /** Positivo aquece o ar, negativo resfria. */
  q_kw: number;
  q_sensivel_kw: number;
  q_latente_kw: number;
  agua_kg_h: number;
  condensado_kg_h: number;
  joelho: PontoProcesso | null;
}

export interface TotaisProcesso {
  vazao_massica_kg_s: number;
  q_aquecimento_kw: number;
  q_refrigeracao_kw: number;
  agua_umidificacao_kg_h: number;
  condensado_kg_h: number;
}

export interface ProcessoAviso {
  codigo: string;
  mensagem: string;
}

/** Medição do painel contra o que o processo dos setpoints prevê (decisões B e D). */
export interface Desvio {
  campo: string;
  ponto: string;
  propriedade: string;
  unidade: string;
  medido: number;
  calculado: number;
  diferenca: number;
}

export interface ProcessoResponse {
  id: number | null;
  simulacao_id: number | null;
  setpoints: Setpoints;
  pontos: PontoProcesso[];
  etapas: EtapaProcesso[];
  totais: TotaisProcesso;
  avisos: ProcessoAviso[];
  desvios: Desvio[];
  /**
   * Entalpia do setpoint de P2 menos a do PID TT04 ENTALPIA (PV) lido/digitado — o par que
   * o gráfico de gasto térmico usa no eixo Delta H. `null` quando o campo não veio na
   * leitura (é opcional no painel).
   */
  delta_h_entalpia: number | null;
  /**
   * Em qual das 4 regiões da estratégia otimizada P1 cai (1 vermelho..4 azul), só para
   * legenda. `null` fora da rota otimizada, ou quando P1 não cai em nenhuma das 4 faixas.
   */
  regiao: number | null;
}

/** Uma linha do histórico gasto térmico × Delta H, para o gráfico e a planilha. */
export interface GastoTermicoHistoricoItem {
  processo_id: number;
  simulacao_id: number;
  /** ISO 8601 em UTC (com sufixo Z). */
  criado_em: string;
  q_aquecimento_kw: number;
  q_refrigeracao_kw: number;
  gasto_termico_kw: number;
  delta_h_entalpia: number | null;
}

export interface GastoTermicoHistoricoResponse {
  itens: GastoTermicoHistoricoItem[];
}

export interface ProcessoInput {
  tbs: number;
  ur: number;
  /** Ausente, usa os setpoints gravados no servidor. */
  setpoints?: Setpoints | null;
  nome?: string;
  descricao?: string | null;
}

/** Incoerência entre campos, detectada depois do OCR. */
export interface MahuAviso {
  codigo: string;
  mensagem: string;
  /** Campos a destacar na conferência. */
  campos: string[];
}

/**
 * Como a foto foi tirada — não o que ela dizia. É o vetor que separa "foto ruim" de
 * "OCR ruim", que pedem correções opostas: uma se resolve guiando a captura, a outra
 * mexendo no reconhecimento.
 */
export interface MahuQualidade {
  /** `homografia` | `quadrilatero` | `resize`, em ordem decrescente de confiabilidade. */
  align_metodo: string;
  align_inliers: number | null;
  /** Erro de reprojeção em pixels do espaço canônico (1200x480), o mesmo das ROIs. */
  align_erro_reproj: number | null;
  /** Pior erro local entre os campos: denuncia o bloco que derivou sozinho. */
  align_erro_reproj_pior: number | null;
  nitidez: number | null;
  reflexo: number | null;
  preenchimento: number | null;
  inclinacao_graus: number | null;
  /** Altura de um dígito em pixels da foto original: a resolução que o OCR teve. */
  px_por_digito: number | null;
}

/** Por que o usuário jogou a leitura fora. Os três primeiros rotulam a FOTO. */
export type MahuMotivoDescarte = "borrada" | "reflexo" | "cortada" | "leu_errado";

/**
 * Veredito sobre um quadro da câmera, antes de qualquer leitura. Uma instrução por vez:
 * quatro avisos ao mesmo tempo viram uma lista de reclamações que a pessoa lê e ignora.
 */
export interface MahuEnquadramento {
  pronto: boolean;
  instrucao: string | null;
  /** Identificador estável do problema — compare por ele, não pelo texto. */
  codigo: string | null;
  qualidade: MahuQualidade;
}

export interface MahuLeituraResponse {
  /** Identifica a leitura na telemetria; volta em `MahuCamposInput.leitura_id`. */
  id: number | null;
  campos: MahuCampoOCR[];
  /**
   * True quando algum campo obrigatório saiu duvidoso OU quando a validação cruzada
   * achou incoerência — o segundo caso pega a leitura em que todos os campos parecem
   * bons isoladamente mas não fecham entre si.
   */
  requires_review: boolean;
  missing_keys: string[];
  avisos: MahuAviso[];
  /** `null` nas leituras gravadas antes da migração 4. */
  qualidade: MahuQualidade | null;
}

/** Campos do painel já conferidos pelo usuário. */
export interface MahuCamposInput {
  mt_01: number;
  tt01: number;
  tt04: number;
  tt06: number;
  mt07: number;
  tt07: number;
  /**
   * Opcionais porque o painel os mostra num bloco de 3 linhas com 17 px entre SP, PV e MV:
   * é o recorte mais arriscado da tela, e falhar neles não pode invalidar os outros seis.
   * Presentes, viram desvio contra o processo e entram no corpus.
   */
  umd_abs_pv?: number | null;
  tt04_entalpia_pv?: number | null;
  /** Liga o aplicado ao sugerido, para o backend rotular o erro de OCR. */
  leitura_id?: number | null;
  /**
   * Tempo com a conferência aberta antes de aplicar. Separa "conferiu e aceitou" de
   * "carimbou sem olhar" — as duas coisas não podem valer como o mesmo rótulo no corpus.
   */
  ms_na_conferencia?: number | null;
}
