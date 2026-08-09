import { http } from "@/lib/http";
import type { LoginInput, Usuario } from "@/types/api";

/**
 * Nenhuma destas funções devolve token: o backend responde com cookies `HttpOnly`, que o
 * JavaScript não consegue ler nem por acidente. É o ponto do desenho — um token guardado em
 * `localStorage` seria lido pelo primeiro XSS que aparecesse.
 */

export async function entrar(credenciais: LoginInput): Promise<Usuario> {
  const { data } = await http.post<Usuario>("/auth/login", credenciais);
  return data;
}

/** Quem está autenticado, ou 401. É a pergunta que o `AuthGate` faz ao abrir a página. */
export async function buscarUsuarioAtual(): Promise<Usuario> {
  const { data } = await http.get<Usuario>("/auth/me");
  return data;
}

export async function sair(): Promise<void> {
  await http.post("/auth/logout");
}

/** Derruba as sessões deste usuário em todos os dispositivos, não só nesta aba. */
export async function sairDeTodosOsDispositivos(): Promise<void> {
  await http.post("/auth/logout-global");
}
