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
  // A sessão vive em cookies HttpOnly. Sem isto o navegador não os anexaria quando o
  // `?api=` aponta para outro host, e toda requisição chegaria anônima.
  withCredentials: true,
});

/** Nome do cookie legível por JavaScript que o backend escreve junto com a sessão. */
const COOKIE_CSRF = "mahu_csrf";
const CABECALHO_CSRF = "X-CSRF-Token";
const METODOS_SEGUROS = new Set(["get", "head", "options"]);

function lerCookie(nome: string): string | null {
  const achado = document.cookie
    .split("; ")
    .find((parte) => parte.startsWith(`${nome}=`));
  return achado ? decodeURIComponent(achado.slice(nome.length + 1)) : null;
}

/**
 * Double-submit de CSRF: repete no cabeçalho o valor do cookie.
 *
 * Autenticação por cookie é enviada pelo navegador sozinha, inclusive em requisição
 * disparada por outro site. `SameSite=Strict` já barra isso; o cabeçalho é o segundo
 * cadeado, e funciona porque outro site consegue provocar a requisição mas não consegue LER
 * o cookie para copiá-lo aqui.
 */
http.interceptors.request.use((config) => {
  if (!METODOS_SEGUROS.has((config.method ?? "get").toLowerCase())) {
    const token = lerCookie(COOKIE_CSRF);
    if (token) {
      config.headers.set(CABECALHO_CSRF, token);
    }
  }
  return config;
});

/**
 * Avisado quando a sessão morre de vez — refresh recusado, ou logout em outra aba.
 *
 * É um callback, e não um import de `useAuthStore`, porque a store precisa do `http` para
 * fazer login: importá-la aqui fecharia um ciclo entre os dois módulos.
 */
let aoPerderSessao: (() => void) | null = null;

export function definirAoPerderSessao(callback: (() => void) | null): void {
  aoPerderSessao = callback;
}

/** Rotas que nunca podem disparar a renovação — seria o laço. */
const ROTAS_DE_AUTENTICACAO = ["/auth/login", "/auth/refresh", "/auth/logout"];

/**
 * Uma renovação por vez. Sem isto, cinco requisições que expirem juntas dispararia cinco
 * `/auth/refresh` em paralelo — e como cada renovação queima o refresh anterior, as quatro
 * atrasadas chegariam com um token já rotacionado. O backend leria isso como cookie clonado
 * e derrubaria a sessão inteira.
 */
let renovacaoEmCurso: Promise<boolean> | null = null;

async function renovarSessao(): Promise<boolean> {
  if (!renovacaoEmCurso) {
    renovacaoEmCurso = http
      .post("/auth/refresh")
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        renovacaoEmCurso = null;
      });
  }
  return renovacaoEmCurso;
}

// Registrado ANTES do tradutor de erro abaixo: os interceptadores rodam na ordem em que
// são adicionados, e este precisa do AxiosError cru para poder refazer a requisição
// original — o ApiError não carrega a configuração dela.
http.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || error.response?.status !== 401) {
      return Promise.reject(error);
    }

    const config = error.config as
      | (typeof error.config & { _jaRenovou?: boolean })
      | undefined;
    const caminho = config?.url ?? "";

    // 401 no login é senha errada, não sessão perdida. Renovar não resolveria, e chamar
    // `aoPerderSessao` faria a tela de login se resetar no meio da digitação.
    if (caminho.startsWith("/auth/login")) {
      return Promise.reject(error);
    }

    // 401 vindo do próprio `/auth/refresh`, ou de uma requisição que já foi renovada uma
    // vez, é veredito final: não há sessão para recuperar.
    if (
      !config ||
      config._jaRenovou ||
      ROTAS_DE_AUTENTICACAO.some((rota) => caminho.startsWith(rota))
    ) {
      aoPerderSessao?.();
      return Promise.reject(error);
    }

    config._jaRenovou = true;
    if (!(await renovarSessao())) {
      aoPerderSessao?.();
      return Promise.reject(error);
    }
    return http.request(config);
  },
);

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
