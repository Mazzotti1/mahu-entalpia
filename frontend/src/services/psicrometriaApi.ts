import { http, isHttpStatus } from "@/lib/http";
import type {
  MahuCamposInput,
  MahuLeituraResponse,
  PontoInput,
  PontoResponse,
  ProcessoInput,
  ProcessoResponse,
  Setpoints,
  SimulacaoInput,
  SimulacaoListaResponse,
  SimulacaoResponse,
} from "@/types/api";

/** O OCR roda em CPU e leva ~20 s; a primeira leitura ainda baixa ~80 MB de modelos. */
const OCR_TIMEOUT_MS = 300_000;

export async function enviarSimulacao(payload: SimulacaoInput): Promise<SimulacaoResponse> {
  const { data } = await http.post<SimulacaoResponse>("/simulacao", payload);
  return data;
}

export async function buscarSimulacao(id: number): Promise<SimulacaoResponse> {
  const { data } = await http.get<SimulacaoResponse>(`/simulacao/${id}`);
  return data;
}

/** Histórico das leituras, da mais recente para a mais antiga. */
export async function listarSimulacoes(
  limite = 30,
  offset = 0,
): Promise<SimulacaoListaResponse> {
  const { data } = await http.get<SimulacaoListaResponse>("/simulacoes", {
    params: { limite, offset },
  });
  return data;
}

export async function calcularPonto(payload: PontoInput): Promise<PontoResponse> {
  const { data } = await http.post<PontoResponse>("/calcular", payload);
  return data;
}

/**
 * `aoProgredirUpload` recebe 0..100 conforme os bytes sobem. Chegando a 100 o upload
 * acabou e o tempo restante é o servidor processando — fase sem progresso mensurável.
 */
export async function lerMahuMonitor(
  file: File,
  aoProgredirUpload?: (porcentagem: number) => void,
): Promise<MahuLeituraResponse> {
  const body = new FormData();
  body.append("image", file);
  const { data } = await http.post<MahuLeituraResponse>("/mahu/ler", body, {
    timeout: OCR_TIMEOUT_MS,
    onUploadProgress: (evento) => {
      // `total` falta quando o tamanho não é conhecido; sem ele não há o que reportar.
      if (!aoProgredirUpload || !evento.total) {
        return;
      }
      aoProgredirUpload(Math.round((evento.loaded / evento.total) * 100));
    },
  });
  return data;
}

/**
 * Resolve o processo a partir dos campos do MAHU já conferidos.
 *
 * Só TT01 e MT_01 alimentam o cálculo — são o ar de entrada. TT_04, TT_06, TT07 e MT07
 * voltam em `desvios`, comparados ao que os setpoints preveem (decisões B e D).
 */
export async function calcularProcessoMahu(campos: MahuCamposInput): Promise<ProcessoResponse> {
  const { data } = await http.post<ProcessoResponse>("/mahu/processo", campos);
  return data;
}

export async function calcularProcesso(payload: ProcessoInput): Promise<ProcessoResponse> {
  const { data } = await http.post<ProcessoResponse>("/processo", payload);
  return data;
}

/**
 * O processo gravado de uma simulação, ou `null` nas anteriores à migração 3 — o histórico
 * tem entradas antigas que nunca tiveram etapas nem kW, e elas ainda precisam abrir.
 */
export async function buscarProcessoDaSimulacao(id: number): Promise<ProcessoResponse | null> {
  try {
    const { data } = await http.get<ProcessoResponse>(`/simulacao/${id}/processo`);
    return data;
  } catch (error) {
    if (isHttpStatus(error, 404)) {
      return null;
    }
    throw error;
  }
}

export async function buscarSetpoints(): Promise<Setpoints> {
  const { data } = await http.get<Setpoints>("/setpoints");
  return data;
}

export async function salvarSetpoints(setpoints: Setpoints): Promise<Setpoints> {
  const { data } = await http.put<Setpoints>("/setpoints", setpoints);
  return data;
}
