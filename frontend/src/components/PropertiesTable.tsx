import { useState } from "react";

import { PontoPopup } from "@/components/PontoPopup";
import { formatarNumero } from "@/lib/format";
import { useChartStore } from "@/store/useChartStore";
import { useProcessoStore } from "@/store/useProcessoStore";
import { SLOT_POR_CAMPO } from "@/types/api";

const COLUNAS = [
  "Ponto",
  "TBS (°C)",
  "W (g/kg)",
  "UR (%)",
  "h (kJ/kg)",
  "TBU (°C)",
  // O orvalho sempre veio da API e nunca era exibido. É ele que localiza o joelho das
  // trajetórias de resfriamento com condensação, então vale a coluna.
  "Orvalho (°C)",
  "Vol. (m³/kg)",
];

export function PropertiesTable() {
  const points = useChartStore((state) => state.points);
  const desvios = useProcessoStore((state) => state.processo?.desvios) ?? [];
  const [selecionado, setSelecionado] = useState<string | null>(null);

  const ponto = points.find((item) => item.nome === selecionado) ?? null;

  return (
    // Escondida no celular deitado: são 7 colunas por 5 linhas, ilegíveis em ~390px de
    // altura, e quem girou o aparelho girou para ver a carta. Em pé ela volta.
    <section className="mt-4 max-w-[1200px] rounded-[10px] border border-gray-200 bg-white p-3 paisagem:hidden">
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
              points.map((item) => (
                <tr
                  key={item.id ?? item.nome}
                  className="cursor-pointer hover:bg-slate-50"
                  onClick={() => setSelecionado(item.nome)}
                  title="Ver fonte (lido/digitado ou calculado) e conferência com o painel"
                >
                  <td className="border border-gray-200 p-2 text-center font-semibold">
                    {item.nome}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.tbs, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.wKgKg * 1000, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.ur, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.entalpia, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.tbu, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.pontoOrvalho, 2)}
                  </td>
                  <td className="border border-gray-200 p-2 text-center tabular-nums">
                    {formatarNumero(item.volumeEspecifico, 3)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {ponto && (
        <PontoPopup
          ponto={ponto}
          // Casa pelos dois nomes do mesmo lugar do MAHU: os desvios voltam rotulados com o
          // ponto da CARTA CALCULADA (P1..P5), e esta tabela lista os pontos da CARTA ATUAL,
          // cujos rótulos são os campos do painel (TT01, TT_04, ...).
          desvios={desvios.filter(
            (desvio) =>
              desvio.ponto === ponto.nome || SLOT_POR_CAMPO[desvio.campo] === ponto.nome,
          )}
          onFechar={() => setSelecionado(null)}
        />
      )}
    </section>
  );
}
