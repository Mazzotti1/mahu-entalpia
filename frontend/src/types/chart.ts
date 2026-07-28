import type { FonteCalculo } from "@/types/api";

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
}

/** Estado sob o cursor (ou o primeiro ponto do processo, quando o mouse sai da carta). */
export interface ProbeState {
  tbs: number;
  wKgKg: number;
}
