/**
 * Trava de orientação da tela.
 *
 * A Screen Orientation API só permite travar a orientação enquanto o documento está em
 * tela cheia — fora dela `lock()` rejeita com NotSupportedError. Por isso as duas coisas
 * andam juntas aqui: entrar em tela cheia é pré-requisito, não enfeite.
 *
 * Consequência prática do fluxo: depois da foto o app NÃO sai da tela cheia, só troca a
 * trava para retrato. Sair devolveria a rotação ao aparelho e o celular voltaria a deitar
 * sozinho — que é exatamente o que se quer evitar. Quem quiser sair usa o gesto do
 * navegador, e aí a trava cai junto, como manda a especificação.
 *
 * Suporte: Chrome/Edge/Firefox no Android travam. O Safari do iOS não implementa
 * `screen.orientation.lock` (nem tela cheia em iPhone), então lá tudo isto vira no-op
 * silencioso e resta a dica de segurar o aparelho deitado. No desktop também é no-op.
 */

type OrientacaoAlvo = "landscape" | "portrait";

/** `lock`/`unlock` não existem em todos os navegadores; o tipo do DOM assume que sim. */
type OrientacaoTravavel = ScreenOrientation & {
  lock?: (orientacao: OrientacaoAlvo) => Promise<void>;
  unlock?: () => void;
};

function orientacaoDaTela(): OrientacaoTravavel | null {
  return (window.screen?.orientation as OrientacaoTravavel | undefined) ?? null;
}

async function entrarEmTelaCheia(): Promise<void> {
  if (document.fullscreenElement) {
    return;
  }
  const raiz = document.documentElement;
  if (!raiz.requestFullscreen) {
    return;
  }
  // navigationUI: "hide" pede para esconder a barra do navegador; onde não for suportado
  // o argumento é ignorado sem erro.
  await raiz.requestFullscreen({ navigationUI: "hide" });
}

/**
 * Trava a tela na orientação pedida, entrando em tela cheia se preciso.
 *
 * Deve ser chamada de dentro de um gesto do usuário (clique): tanto `requestFullscreen`
 * quanto `lock` exigem ativação. Falha é engolida de propósito — o app funciona sem a
 * trava, e um erro aqui não é acionável para quem está com o celular na mão.
 */
export async function travarOrientacao(alvo: OrientacaoAlvo): Promise<void> {
  try {
    await entrarEmTelaCheia();
    await orientacaoDaTela()?.lock?.(alvo);
  } catch {
    // Sem suporte (iOS, desktop) ou sem gesto válido: segue sem travar.
  }
}

/** Solta a trava e sai da tela cheia. Só para quando o app for realmente encerrar o fluxo. */
export async function liberarOrientacao(): Promise<void> {
  try {
    orientacaoDaTela()?.unlock?.();
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    }
  } catch {
    // Idem: nada a fazer se o navegador recusar.
  }
}
