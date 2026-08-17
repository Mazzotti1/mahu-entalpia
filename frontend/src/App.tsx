import { useState } from "react";

import { ComparacaoPanel } from "@/components/ComparacaoPanel";
import { EntalpiaSpInput } from "@/components/EntalpiaSpInput";
import { HistoryPanel } from "@/components/HistoryPanel";
import { IndicatorPanel } from "@/components/IndicatorPanel";
import { LayerTogglesPanel } from "@/components/LayerTogglesPanel";
import { MahuPanel } from "@/components/MahuPanel";
import { PropertiesTable } from "@/components/PropertiesTable";
import { PsychrometricChart } from "@/components/PsychrometricChart";
import { SetpointsPanel } from "@/components/SetpointsPanel";
import { useAuthStore } from "@/store/useAuthStore";
import { useChartStoreOtimizada } from "@/store/useChartStore";
import { useProcessoStore } from "@/store/useProcessoStore";

/** Quem está logado e a saída. A autoria das leituras vai para o banco: convém saber sob
 * qual conta se está gravando antes de fotografar o painel.
 */
function ContaAtual() {
  const usuario = useAuthStore((state) => state.usuario);
  const sair = useAuthStore((state) => state.sair);

  if (!usuario) {
    return null;
  }

  return (
    <span className="flex shrink-0 items-baseline gap-2 text-xs text-gray-600">
      <span className="truncate" title={usuario.username}>
        {usuario.username}
      </span>
      <button
        type="button"
        onClick={() => void sair()}
        className="cursor-pointer text-blue-700 underline"
      >
        Sair
      </button>
    </span>
  );
}

// Descrevem em que zona o ar de ENTRADA caiu, e só isso. Antes traziam o alvo de entalpia
// de cada região ("aquecer até 28 kJ/kg"), porque era uma tabela de alvos que decidia a
// carta otimizada. Não é mais: o alvo agora é deduzido (ver `otimizacao.py`), e repetir
// aqueles números descreveria um algoritmo que saiu do código.
const ROTULOS_REGIAO: Record<number, string> = {
  1: "Região 1 (vermelho) — ar de entrada frio e seco",
  2: "Região 2 (laranja) — ar de entrada quente e seco",
  3: "Região 3 (verde) — ar de entrada frio e úmido",
  4: "Região 4 (azul) — ar de entrada quente e úmido",
};

/** Em qual das 4 zonas o ar de entrada caiu. Rótulo, não decisão de cálculo. */
function LegendaRegiao() {
  const regiao = useProcessoStore((state) => state.regiaoOtimizada);
  if (regiao == null) {
    return null;
  }
  return (
    <p className="text-[12px] text-slate-600 paisagem:hidden">
      {ROTULOS_REGIAO[regiao] ?? `Região ${regiao}`}
    </p>
  );
}

/**
 * Dois modos, e a variante `paisagem` decide qual:
 *
 * em pé (e no desktop) o painel fica visível o tempo todo, ao lado ou acima da carta;
 * deitado no celular a carta toma a tela inteira e o painel vira gaveta. Quem gira o
 * aparelho está pedindo para ver o gráfico maior — deixar o painel empilhado por cima,
 * como acontecia antes, gastava a altura que a rotação tinha acabado de conseguir.
 *
 * No desktop, a sidebar ganha o mesmo tipo de gaveta: as duas cartas (ATUAL e OTIMIZADA)
 * lado a lado precisam do espaço que ela ocupa, então fechá-la também é uma opção aqui —
 * um estado à parte do `painelAberto` de paisagem, para não misturar os dois breakpoints.
 *
 * As duas cartas partem do MESMO ar: a ATUAL encadeia os instrumentos do painel do começo
 * ao fim; a OTIMIZADA copia os dois primeiros pontos dela — entrada e pré-aquecimento, que
 * já aconteceram quando a foto foi tirada — e daí em diante segue a rota mais barata até os
 * setpoints. A comparação logo abaixo é o assunto da tela: a diferença entre as duas é
 * dinheiro que a operação atual está deixando na mesa.
 */
export default function App() {
  const [painelAberto, setPainelAberto] = useState(false);
  const [sidebarAbertaDesktop, setSidebarAbertaDesktop] = useState(true);

  const processoMedido = useProcessoStore((state) => state.processoMedido);
  const processoOtimizado = useProcessoStore((state) => state.processoOtimizado);
  const entalpiaSpAtual = useProcessoStore((state) => state.entalpiaSpAtual);
  const entalpiaSpOtimizada = useProcessoStore((state) => state.entalpiaSpOtimizada);
  const definirEntalpiaSpAtual = useProcessoStore((state) => state.definirEntalpiaSpAtual);
  const definirEntalpiaSpOtimizada = useProcessoStore(
    (state) => state.definirEntalpiaSpOtimizada,
  );

  return (
    <main className="flex min-h-screen flex-col desk:flex-row paisagem:h-dvh paisagem:min-h-0 paisagem:flex-row paisagem:overflow-hidden">
      <aside
        className={`border-b border-gray-300 bg-gray-100 p-4 desk:w-[300px] desk:shrink-0 desk:overflow-y-auto desk:border-r desk:border-b-0 paisagem:w-[280px] paisagem:shrink-0 paisagem:overflow-y-auto paisagem:border-r paisagem:border-b-0 ${
          painelAberto ? "" : "paisagem:hidden"
        } ${sidebarAbertaDesktop ? "" : "desk:hidden"}`}
      >
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h1 className="text-2xl font-semibold paisagem:text-lg">PSICROMETRIA</h1>
          <ContaAtual />
        </div>
        <MahuPanel />
        <SetpointsPanel />
        <HistoryPanel />
        <IndicatorPanel />
        <LayerTogglesPanel />
      </aside>

      <section className="flex min-w-0 flex-1 flex-col p-4 paisagem:min-h-0 paisagem:p-2">
        <header className="flex items-center gap-2">
          {/* Só aparece em paisagem: é lá que o painel some e precisa de um caminho de volta. */}
          <button
            type="button"
            onClick={() => setPainelAberto((aberto) => !aberto)}
            className="hidden rounded-md border border-gray-300 bg-white px-2 py-1 text-sm paisagem:block"
            aria-expanded={painelAberto}
          >
            {painelAberto ? "Ocultar painel" : "Painel"}
          </button>
          {/* Só aparece no desktop: liberar a largura das duas cartas lado a lado. */}
          <button
            type="button"
            onClick={() => setSidebarAbertaDesktop((aberta) => !aberta)}
            className="hidden rounded-md border border-gray-300 bg-white px-2 py-1 text-sm desk:block"
            aria-expanded={sidebarAbertaDesktop}
          >
            {sidebarAbertaDesktop ? "Ocultar painel" : "Painel"}
          </button>
          <h2 className="mb-2 text-[28px] font-semibold paisagem:mb-0 paisagem:text-base">
            Carta psicrométrica
          </h2>
        </header>

        <div className="flex flex-col gap-4 cartas:flex-row">
          <div className="flex min-w-0 flex-1 flex-col">
            <h3 className="mb-1 text-sm font-semibold text-slate-700">CARTA ATUAL</h3>
            <p className="text-[12px] text-slate-600 paisagem:hidden">
              Pontos estritamente digitados/capturados do painel.
            </p>
            <EntalpiaSpInput
              valor={entalpiaSpAtual}
              aoConfirmar={definirEntalpiaSpAtual}
              ajuda="O SP que a planta está perseguindo. Vai junto com a próxima leitura e volta como desvio; não move os pontos desta carta, que vêm todos de instrumento."
            />
            <PsychrometricChart />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <h3 className="mb-1 text-sm font-semibold text-slate-700">CARTA OTIMIZADA</h3>
            <p className="text-[12px] text-slate-600 paisagem:hidden">
              Parte dos pontos 1 e 2 da atual; do 3º em diante, a rota de menor custo.
            </p>
            <LegendaRegiao />
            <EntalpiaSpInput
              valor={entalpiaSpOtimizada}
              aoConfirmar={(valor) => void definirEntalpiaSpOtimizada(valor)}
              ajuda="Em branco, o algoritmo escolhe o alvo mais barato. Digitar um valor desliga a otimização e simula esse alvo — qualquer um que não seja o ótimo custa mais."
            />
            <PsychrometricChart useStore={useChartStoreOtimizada} mostrarRegioes />
          </div>
        </div>

        <ComparacaoPanel atual={processoMedido} otimizado={processoOtimizado} />
        <PropertiesTable />
      </section>
    </main>
  );
}
