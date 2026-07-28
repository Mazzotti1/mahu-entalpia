import { http } from "@/lib/http";
import type {
  MahuCamposInput,
  MahuLeituraResponse,
  PontoInput,
  PontoResponse,
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
 * Calcula e persiste a simulação a partir dos campos do MAHU já conferidos. Quem traduz
 * campo do painel em P1..P4 continua sendo o backend (`services/mahu.py`).
 */
export async function criarSimulacaoMahu(campos: MahuCamposInput): Promise<SimulacaoResponse> {
  const { data } = await http.post<SimulacaoResponse>("/mahu/simulacao", campos);
  return data;
}
