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
 * - `ok`: variantes de pré-processamento concordaram e o valor é plausível
 * - `low_confidence`: valor plausível, mas leitura fraca
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
}

export interface MahuLeituraResponse {
  campos: MahuCampoOCR[];
  missing_keys: string[];
  /** True quando algum campo obrigatório saiu duvidoso: exige conferência manual. */
  requires_review: boolean;
  suggested_simulacao: SimulacaoInput | null;
}

/** Campos obrigatórios de `MahuCamposInput`, já conferidos pelo usuário. */
export interface MahuCamposInput {
  mt_01: number;
  tt01: number;
  tt04: number;
  tt06: number;
  mt07: number;
  tt07: number;
}
