import { formatarNumero } from "@/lib/format";
import { useProcessoStore } from "@/store/useProcessoStore";
import type { EtapaProcesso } from "@/types/api";

const ROTULO_ETAPA: Record<EtapaProcesso["tipo"], string> = {
  resfriamento_sensivel: "Resfriamento sensível",
  resfriamento_desumidificacao: "Resfriamento + desumidificação",
  aquecimento_sensivel: "Aquecimento sensível",
  umidificacao_adiabatica: "Umidificação adiabática",
  nula: "Etapa pulada",
};

const COR_ETAPA: Record<EtapaProcesso["tipo"], string> = {
  resfriamento_sensivel: "text-sky-700",
  resfriamento_desumidificacao: "text-blue-700",
  aquecimento_sensivel: "text-rose-700",
  umidificacao_adiabatica: "text-emerald-700",
  nula: "text-slate-400",
};

function Destaque({
  rotulo,
  valor,
  unidade,
  cor,
}: {
  rotulo: string;
  valor: number;
  unidade: string;
  cor: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-slate-50 p-2">
      <div className="text-[11px] text-slate-500">{rotulo}</div>
      <div className={`text-lg font-semibold tabular-nums ${cor}`}>
        {formatarNumero(valor, 1)} <span className="text-xs font-normal">{unidade}</span>
      </div>
    </div>
  );
}

export function ThermalLoadPanel() {
  const processo = useProcessoStore((state) => state.processo);

  if (!processo) {
    return null;
  }

  const { totais, etapas, avisos, desvios } = processo;

  return (
    <section className="mt-4 max-w-[1200px] rounded-[10px] border border-gray-200 bg-white p-3 paisagem:hidden">
      <h3 className="mb-2.5 text-lg font-semibold">Gasto térmico</h3>

      {avisos.length > 0 && (
        <ul className="mb-3 space-y-1">
          {avisos.map((aviso) => (
            <li
              key={aviso.codigo}
              className="rounded-md border border-amber-400 bg-amber-50 px-2 py-1.5 text-[12px] text-amber-900"
            >
              {aviso.mensagem}
            </li>
          ))}
        </ul>
      )}

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Destaque
          rotulo="Refrigeração"
          valor={totais.q_refrigeracao_kw}
          unidade="kW"
          cor="text-blue-700"
        />
        <Destaque
          rotulo="Aquecimento"
          valor={totais.q_aquecimento_kw}
          unidade="kW"
          cor="text-rose-700"
        />
        <Destaque
          rotulo="Condensado"
          valor={totais.condensado_kg_h}
          unidade="kg/h"
          cor="text-slate-700"
        />
        <Destaque
          rotulo="Água de umidificação"
          valor={totais.agua_umidificacao_kg_h}
          unidade="kg/h"
          cor="text-emerald-700"
        />
      </div>

      <p className="mb-2 text-[12px] text-slate-500">
        Vazão de ar seco: {formatarNumero(totais.vazao_massica_kg_s, 3)} kg/s, de{" "}
        {formatarNumero(processo.setpoints.vazao_m3h, 0)} m³/h medidos na entrada.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-slate-50">
            <tr>
              {["Etapa", "Transformação", "Q (kW)", "Sensível", "Latente", "Água (kg/h)"].map(
                (coluna) => (
                  <th
                    key={coluna}
                    className="border border-gray-200 p-2 text-center font-semibold"
                  >
                    {coluna}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {etapas.map((etapa) => (
              <tr key={`${etapa.de}-${etapa.para}`} className={etapa.ativa ? "" : "opacity-50"}>
                <td className="border border-gray-200 p-2 text-center font-semibold">
                  {etapa.de} → {etapa.para}
                </td>
                <td className={`border border-gray-200 p-2 ${COR_ETAPA[etapa.tipo]}`}>
                  {ROTULO_ETAPA[etapa.tipo]}
                </td>
                <td className="border border-gray-200 p-2 text-center font-semibold tabular-nums">
                  {etapa.ativa ? formatarNumero(etapa.q_kw, 2) : "—"}
                </td>
                <td className="border border-gray-200 p-2 text-center tabular-nums">
                  {etapa.ativa ? formatarNumero(etapa.q_sensivel_kw, 2) : "—"}
                </td>
                <td className="border border-gray-200 p-2 text-center tabular-nums">
                  {etapa.ativa ? formatarNumero(etapa.q_latente_kw, 2) : "—"}
                </td>
                <td className="border border-gray-200 p-2 text-center tabular-nums">
                  {etapa.agua_kg_h > 0
                    ? `+${formatarNumero(etapa.agua_kg_h, 1)}`
                    : etapa.condensado_kg_h > 0
                      ? `−${formatarNumero(etapa.condensado_kg_h, 1)}`
                      : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-[11px] text-slate-500">
        Q negativo retira calor do ar. A umidificação adiabática fica fora dos totais de kW:
        o calor dela vem do próprio ar, e o custo aparece como água.
      </p>

      {desvios.length > 0 && (
        <>
          <h4 className="mt-4 mb-2 text-sm font-semibold">
            Desvio do painel em relação aos setpoints
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-slate-50">
                <tr>
                  {["Campo", "Ponto", "Medido", "Calculado", "Diferença"].map((coluna) => (
                    <th
                      key={coluna}
                      className="border border-gray-200 p-2 text-center font-semibold"
                    >
                      {coluna}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {desvios.map((desvio) => (
                  <tr key={desvio.campo}>
                    <td className="border border-gray-200 p-2 text-center font-semibold">
                      {desvio.campo.toUpperCase()}
                    </td>
                    <td className="border border-gray-200 p-2 text-center">
                      {desvio.ponto} · {desvio.propriedade}
                    </td>
                    <td className="border border-gray-200 p-2 text-center tabular-nums">
                      {formatarNumero(desvio.medido, 2)} {desvio.unidade}
                    </td>
                    <td className="border border-gray-200 p-2 text-center tabular-nums">
                      {formatarNumero(desvio.calculado, 2)} {desvio.unidade}
                    </td>
                    <td
                      className={`border border-gray-200 p-2 text-center font-semibold tabular-nums ${
                        Math.abs(desvio.diferenca) > 1 ? "text-amber-700" : "text-slate-600"
                      }`}
                    >
                      {desvio.diferenca > 0 ? "+" : ""}
                      {formatarNumero(desvio.diferenca, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            O processo é calculado a partir dos setpoints. Estas medições do painel servem
            para conferir se a planta está cumprindo o controle.
          </p>
        </>
      )}
    </section>
  );
}
