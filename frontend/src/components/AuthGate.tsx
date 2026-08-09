import { useEffect, type ReactNode } from "react";

import { LoginScreen } from "@/components/LoginScreen";
import { useAuthStore } from "@/store/useAuthStore";

/**
 * O portão de toda a aplicação. Sem sessão, `children` não chega a ser montado — e é isso
 * que importa: um painel escondido por CSS continuaria buscando dados, e a decisão de quem
 * pode ver o quê estaria no navegador, onde qualquer um a desfaz pelo DevTools.
 *
 * A defesa de verdade está no backend, onde cada rota exige sessão válida. Este componente
 * não protege dado nenhum: ele evita que a pessoa encare uma tela de erros enquanto o
 * backend nega uma requisição atrás da outra.
 *
 * Não há rota nem router aqui porque a aplicação é uma tela só. Entrando mais telas, este é
 * o ponto onde um `<RotaProtegida>` entraria.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const usuario = useAuthStore((state) => state.usuario);
  const verificando = useAuthStore((state) => state.verificando);
  const verificarSessao = useAuthStore((state) => state.verificarSessao);

  useEffect(() => {
    void verificarSessao();
  }, [verificarSessao]);

  if (verificando) {
    // Mostrar o login antes da resposta faria a tela piscar em todo recarregamento de quem
    // já está autenticado — o cookie existe, mas só o servidor sabe se ele ainda vale.
    return (
      <main className="flex min-h-dvh items-center justify-center bg-gray-100">
        <p className="text-sm text-gray-600">Verificando sessão…</p>
      </main>
    );
  }

  return usuario ? <>{children}</> : <LoginScreen />;
}
