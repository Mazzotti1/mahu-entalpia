import { HistoryPanel } from "@/components/HistoryPanel";
import { IndicatorPanel } from "@/components/IndicatorPanel";
import { LayerTogglesPanel } from "@/components/LayerTogglesPanel";
import { MahuPanel } from "@/components/MahuPanel";
import { PropertiesTable } from "@/components/PropertiesTable";
import { PsychrometricChart } from "@/components/PsychrometricChart";

export default function App() {
  return (
    <main className="grid min-h-screen grid-cols-1 desk:grid-cols-[300px_1fr]">
      <aside className="border-b border-gray-300 bg-gray-100 p-4 desk:border-r desk:border-b-0">
        <h1 className="mb-3 text-2xl font-semibold">PSICROMETRIA</h1>
        <MahuPanel />
        <HistoryPanel />
        <IndicatorPanel />
        <LayerTogglesPanel />
      </aside>

      <section className="p-4">
        <header>
          <h2 className="mb-2 text-[28px] font-semibold">Carta psicrométrica</h2>
        </header>
        <PsychrometricChart />
        <PropertiesTable />
      </section>
    </main>
  );
}
