import { create } from "zustand";

import { definirAoPerderSessao, describeError, isHttpStatus } from "@/lib/http";
import {
  buscarUsuarioAtual,
  entrar as entrarApi,
  sair as sairApi,
} from "@/services/autenticacaoApi";
import type { Usuario } from "@/types/api";

interface AuthState {
  usuario: Usuario | null;
  /** True até a primeira resposta de `/auth/me`. Enquanto isso não se sabe de nada. */
  verificando: boolean;
  entrando: boolean;
  erro: string | null;

  verificarSessao: () => Promise<void>;
  entrar: (username: string, senha: string) => Promise<void>;
  sair: () => Promise<void>;
  /** Chamado de fora quando o servidor recusa a sessão: refresh negado ou SSE derrubado. */
  sessaoPerdida: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  usuario: null,
  verificando: true,
  entrando: false,
  erro: null,

  /**
   * Pergunta ao backend se já existe sessão. É o que evita piscar a tela de login para quem
   * recarrega a página autenticado — o cookie está lá, mas só o servidor sabe se ele vale.
   *
   * Um 401 aqui é resposta normal, não falha: significa "não está logado". O interceptador
   * do `http` já tentou renovar antes de o erro chegar até aqui.
   */
  verificarSessao: async () => {
    try {
      set({ usuario: await buscarUsuarioAtual(), erro: null });
    } catch (error) {
      set({ usuario: null, erro: isHttpStatus(error, 401) ? null : describeError(error) });
    } finally {
      set({ verificando: false });
    }
  },

  entrar: async (username, senha) => {
    if (get().entrando) {
      return;
    }
    set({ entrando: true, erro: null });
    try {
      set({ usuario: await entrarApi({ username, senha }) });
    } catch (error) {
      // A mensagem vem do backend e é a mesma para usuário inexistente, senha errada e
      // conta desativada. Reescrevê-la aqui reintroduziria a enumeração que o backend
      // tomou o cuidado de fechar.
      set({ usuario: null, erro: describeError(error) });
    } finally {
      set({ entrando: false });
    }
  },

  sair: async () => {
    try {
      await sairApi();
    } catch {
      // Falhar em avisar o servidor não pode prender ninguém na aplicação: o estado local
      // vai para deslogado de qualquer forma, e a sessão morre sozinha no vencimento.
    }
    set({ usuario: null, erro: null, verificando: false });
  },

  sessaoPerdida: () => {
    if (get().usuario === null) {
      return;
    }
    set({
      usuario: null,
      verificando: false,
      erro: "Sua sessão expirou. Entre novamente.",
    });
  },
}));

// Fecha o laço com o interceptador de 401: ele não pode importar esta store (a store usa o
// `http` para o login, e o import seria circular), então recebe a função por aqui.
definirAoPerderSessao(() => useAuthStore.getState().sessaoPerdida());
