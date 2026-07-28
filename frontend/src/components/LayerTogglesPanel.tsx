import { CHART_LAYERS } from "@/chart/layers";
import { Panel } from "@/components/ui/Panel";
import { useChartStore } from "@/store/useChartStore";

export function LayerTogglesPanel() {
  const layers = useChartStore((state) => state.layers);
  const toggleLayer = useChartStore((state) => state.toggleLayer);

  return (
    <Panel title="Métricas do gráfico">
      {CHART_LAYERS.map((layer) => (
        <label key={layer.key} className="flex cursor-pointer items-center gap-2 py-1.5 text-sm">
          <input
            type="checkbox"
            checked={layers[layer.key]}
            onChange={() => toggleLayer(layer.key)}
            className="size-4 accent-blue-600"
          />
          {layer.label}
        </label>
      ))}
    </Panel>
  );
}
