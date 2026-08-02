import axios, { AxiosError } from "axios";

/** Chamadas comuns respondem em milissegundos; o OCR passa desse teto e usa o seu próprio. */
const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * O nginx (produção) e o dev server do Vite fazem proxy de `/api` para o backend, então
 * caminho relativo basta e não há CORS. `?api=` permite apontar para outro host sem
 * rebuild — útil ao abrir a página pelo celular durante o desenvolvimento.
 */
function resolveBaseUrl(): string {
  const override = new URLSearchParams(window.location.search).get("api");
  if (override) {
    return `${override.replace(/\/+$/, "")}/api`;
  }
  return import.meta.env.VITE_API_BASE_URL ?? "/api";
}

interface FastApiValidationItem {
  loc?: (string | number)[];
  msg: string;
}

interface FastApiErrorBody {
  detail?: string | FastApiValidationItem[];
}

/** Traduz a resposta de erro do FastAPI na mensagem que vai para a tela. */
function describeApiError(error: AxiosError<FastApiErrorBody>): string {
  const response = error.response;
  if (!response) {
    if (error.code === AxiosError.ECONNABORTED) {
      return "A API demorou demais para responder.";
    }
    return "Não foi possível falar com a API. Verifique se o backend está no ar.";
  }

  const detail = response.data?.detail;
  if (typeof detail === "string") {
    return detail;
  }
  // Erro de validação do FastAPI (422): detail é uma lista de {loc, msg}. O primeiro
  // item de `loc` é sempre o corpo/query, por isso o slice.
  if (Array.isArray(detail)) {
    return detail
      .map((item) => `${(item.loc ?? []).slice(1).join(".") || "campo"}: ${item.msg}`)
      .join("; ");
  }
  return `Falha na API (${response.status})`;
}

/**
 * Erro de API com a mensagem já pronta para a tela. Carrega o `status` porque há resposta
 * que não é falha: um 404 em "esta simulação tem processo?" é a resposta "não tem", e sem
 * o código quem chama teria de adivinhar isso pelo texto da mensagem.
 */
export class ApiError extends Error {
  // Campo declarado e atribuído no corpo, e não parâmetro de construtor: o projeto roda
  // com `erasableSyntaxOnly`, que proíbe a forma abreviada.
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isHttpStatus(error: unknown, status: number): boolean {
  return error instanceof ApiError && error.status === status;
}

export const http = axios.create({
  baseURL: resolveBaseUrl(),
  timeout: DEFAULT_TIMEOUT_MS,
});

// Rejeita sempre com um Error de mensagem pronta: quem chama não precisa conhecer axios.
http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError<FastApiErrorBody>(error)) {
      return Promise.reject(
        new ApiError(describeApiError(error), error.response?.status ?? null),
      );
    }
    return Promise.reject(error instanceof Error ? error : new Error(String(error)));
  },
);

/**
 * URL absoluta de uma rota da API. O `EventSource` não usa o axios, então precisa da base
 * resolvida na mão — inclusive quando `?api=` aponta para outro host.
 */
export function streamUrl(caminho: string): string {
  return `${resolveBaseUrl()}${caminho}`;
}

export function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Falha desconhecida.";
}
