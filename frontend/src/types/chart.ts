import type { EtapaProcesso, FonteCalculo, FontePonto } from "@/types/api";

/**
 * Ponto do processo já normalizado para o desenho. `wKgKg` guarda kg/kg (a unidade das
 * fórmulas) e só vira g/kg na plotagem e na tabela — o backend responde em g/kg.
 */
export interface ProcessPoint {
  id: number | null;
  nome: string;
  tbs: number;
  wKgKg: number;
  ur: number;
  entalpia: number;
  tbu: number;
  volumeEspecifico: number;
  pontoOrvalho: number;
  fonteCalculo: FonteCalculo;
  /** Lido/digitado no painel (só P1) ou calculado a partir dos setpoints (P2..P5). */
  fonte: FontePonto;
  saturado?: boolean;
}

/**
 * Uma etapa pronta para desenhar. Guarda os estados nas coordenadas do canvas para o
 * traçado não ter de reconsultar a resposta da API a cada quadro.
 */
export interface ProcessSegment {
  tipo: EtapaProcesso["tipo"];
  de: string;
  para: string;
  inicio: { tbs: number; wGkg: number };
  fim: { tbs: number; wGkg: number };
  /** Onde a trajetória dobra sobre a saturação; ausente quando o trecho é uma reta só. */
  joelho: { tbs: number; wGkg: number } | null;
}

/** Estado sob o cursor (ou o primeiro ponto do processo, quando o mouse sai da carta). */
export interface ProbeState {
  tbs: number;
  wKgKg: number;
}
