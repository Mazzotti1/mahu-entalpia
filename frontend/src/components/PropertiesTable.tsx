import { formatarNumero } from "@/lib/format";
import { useChartStore } from "@/store/useChartStore";

const COLUNAS = [
  "Ponto",
  "TBS (°C)",
  "W (g/kg)",
  "UR (%)",
  "h (kJ/kg)",
  "TBU (°C)",
  "Vol. (m³/kg)",
];

export function PropertiesTable() {
  const points = useChartStore((state) => state.points);

  return (
    <section className="mt-4 max-w-[1200px] rounded-[10px] border border-gray-200 bg-white p-3">
      <h3 className="mb-2.5 text-lg font-semibold">Tabela de propriedades calculadas</h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-slate-50">
            <tr>
              {COLUNAS.map((coluna) => (
                <th key={coluna} className="border border-gray-200 p-2 text-center font-semibold">
                  {coluna}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.length === 0 ? (
              <tr>
                <td
                  colSpan={COLUNAS.length}
                  className="border border-gray-200 p-2 text-center text-slate-500"
                >
                  Nenhum ponto calculado.
                </td>
              </tr>
            ) : (
              points.map((ponto) => (
                <tr key={ponto.id ?? ponto.nome}>
                  <td className="border border-gray-200 p-2 text-center font-semibold">
                    {ponto.nome}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(ponto.tbs, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(ponto.wKgKg * 1000, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(ponto.ur, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(ponto.entalpia, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(ponto.tbu, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(ponto.volumeEspecifico, 3)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
