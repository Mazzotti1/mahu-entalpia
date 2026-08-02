/** Espelho dos modelos Pydantic de `backend/models.py`. */

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
  /** Vazão volumétrica medida na ENTRADA (decisão A), m³/h. */
  vazao_m3h: number;
  /** Pressão atmosférica em Pa — não em kPa. */
  pressao_atm: number;
}

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
}

/** Campos obrigatórios de `MahuCamposInput`, já conferidos pelo usuário. */
export interface MahuCamposInput {
  mt_01: number;
  tt01: number;
  tt04: number;
  tt06: number;
  mt07: number;
  tt07: number;
  /** Liga o aplicado ao sugerido, para o backend rotular o erro de OCR. */
  leitura_id?: number | null;
}
