import { useState, type FormEvent } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { useAuthStore } from "@/store/useAuthStore";

const CAMPO =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-600";

/**
 * Não há link de cadastro nem de "esqueci minha senha", e é de propósito: as contas são
 * criadas no servidor por `scripts/criar_usuario.py`. Um fluxo de recuperação por e-mail,
 * para um punhado de operadores, seria mais superfície de ataque do que conveniência.
 */
export function LoginScreen() {
  const [username, setUsername] = useState("");
  const [senha, setSenha] = useState("");

  const entrar = useAuthStore((state) => state.entrar);
  const entrando = useAuthStore((state) => state.entrando);
  const erro = useAuthStore((state) => state.erro);

  const enviar = (evento: FormEvent) => {
    evento.preventDefault();
    void entrar(username, senha);
  };

  return (
    <main className="flex min-h-dvh items-center justify-center bg-gray-100 p-4">
      <form
        onSubmit={enviar}
        className="w-full max-w-sm rounded-[10px] border border-gray-200 bg-white p-6"
      >
        <h1 className="text-2xl font-semibold">PSICROMETRIA</h1>
        <p className="mt-1 mb-5 text-sm text-gray-600">Entre para acessar o simulador.</p>

        <label className="mb-1 block text-sm font-medium" htmlFor="username">
          Usuário
        </label>
        <input
          id="username"
          name="username"
          value={username}
          onChange={(evento) => setUsername(evento.target.value)}
          // O gerenciador de senhas do navegador só reconhece o par pelos `autoComplete`
          // corretos; sem eles ele oferece salvar a senha no campo errado, ou não oferece.
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
          disabled={entrando}
          className={CAMPO}
        />

        <label className="mt-4 mb-1 block text-sm font-medium" htmlFor="senha">
          Senha
        </label>
        <input
          id="senha"
          name="senha"
          type="password"
          value={senha}
          onChange={(evento) => setSenha(evento.target.value)}
          autoComplete="current-password"
          required
          disabled={entrando}
          className={CAMPO}
        />

        {erro ? (
          // `role="alert"` para o leitor de tela anunciar a recusa: quem não vê a tela
          // ficaria com o formulário aparentemente intacto e sem saber que falhou.
          <p role="alert" className="mt-4 text-sm text-red-700">
            {erro}
          </p>
        ) : null}

        <ActionButton type="submit" disabled={entrando} className="mt-5 w-full">
          {entrando ? "Entrando…" : "Entrar"}
        </ActionButton>
      </form>
    </main>
  );
}
