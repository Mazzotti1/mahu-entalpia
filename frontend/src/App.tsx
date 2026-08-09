import { useState } from "react";

import { GastoTermicoChart } from "@/components/GastoTermicoChart";
import { HistoryPanel } from "@/components/HistoryPanel";
import { IndicatorPanel } from "@/components/IndicatorPanel";
import { LayerTogglesPanel } from "@/components/LayerTogglesPanel";
import { MahuPanel } from "@/components/MahuPanel";
import { PropertiesTable } from "@/components/PropertiesTable";
import { PsychrometricChart } from "@/components/PsychrometricChart";
import { SetpointsPanel } from "@/components/SetpointsPanel";
import { ThermalLoadPanel } from "@/components/ThermalLoadPanel";
import { useAuthStore } from "@/store/useAuthStore";

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

/**
 * Dois modos, e a variante `paisagem` decide qual:
 *
 * em pé (e no desktop) o painel fica visível o tempo todo, ao lado ou acima da carta;
 * deitado no celular a carta toma a tela inteira e o painel vira gaveta. Quem gira o
 * aparelho está pedindo para ver o gráfico maior — deixar o painel empilhado por cima,
 * como acontecia antes, gastava a altura que a rotação tinha acabado de conseguir.
 */
export default function App() {
  const [painelAberto, setPainelAberto] = useState(false);

  return (
    <main className="flex min-h-screen flex-col desk:flex-row paisagem:h-dvh paisagem:min-h-0 paisagem:flex-row paisagem:overflow-hidden">
      <aside
        className={`border-b border-gray-300 bg-gray-100 p-4 desk:w-[300px] desk:shrink-0 desk:overflow-y-auto desk:border-r desk:border-b-0 paisagem:w-[280px] paisagem:shrink-0 paisagem:overflow-y-auto paisagem:border-r paisagem:border-b-0 ${
          painelAberto ? "" : "paisagem:hidden"
        }`}
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
          <h2 className="mb-2 text-[28px] font-semibold paisagem:mb-0 paisagem:text-base">
            Carta psicrométrica
          </h2>
        </header>

        <PsychrometricChart />
        <ThermalLoadPanel />
        <PropertiesTable />
        <GastoTermicoChart />
      </section>
    </main>
  );
}
