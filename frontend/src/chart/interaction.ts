import { chartConfig, getPlotBounds, xToTbs, yToW } from "@/chart/config";
import { urParaW } from "@/lib/psicrometria";
import type { ProbeState } from "@/types/chart";

/**
 * Converte a posição do ponteiro no estado psicrométrico sob ele, ou `null` quando o
 * ponteiro está fora da área útil ou na região supersaturada (acima da curva de 100%),
 * que não representa ar úmido possível.
 */
export function probeFromPointer(
  canvas: HTMLCanvasElement,
  clientX: number,
  clientY: number,
): ProbeState | null {
  // O canvas é escalado pelo CSS: sem esse fator o cursor "anda" fora do ponto lido.
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return null;
  }
  const x = (clientX - rect.left) * (chartConfig.width / rect.width);
  const y = (clientY - rect.top) * (chartConfig.height / rect.height);

  const plot = getPlotBounds();
  if (x < plot.left || x > plot.right || y < plot.top || y > plot.bottom) {
    return null;
  }

  const tbs = xToTbs(x);
  const wGkg = yToW(y);
  if (wGkg < 0 || wGkg > urParaW(100, tbs) * 1000) {
    return null;
  }

  return { tbs, wKgKg: wGkg / 1000 };
}
