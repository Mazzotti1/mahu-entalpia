import { formatarNumero } from "@/lib/format";
import type { Desvio } from "@/types/api";
import type { ProcessPoint } from "@/types/chart";

interface PontoPopupProps {
  ponto: ProcessPoint;
  desvios: Desvio[];
  onFechar: () => void;
}

const ROTULO_FONTE: Record<ProcessPoint["fonte"], string> = {
  lido_digitado: "Lido/digitado no painel",
  calculado: "Calculado a partir dos setpoints",
};

/**
 * Detalhe de um ponto ao clicar no indicador: o valor, se é lido/digitado ou calculado, e
 * — quando existe — a conferência contra o campo do painel que descreve o mesmo estado
 * (TT_04/TT_06/TT07/MT07 e os PIDs). Sem isso essa comparação só existia na tabela de
 * "Desvio do painel", solta do ponto a que se refere.
 */
export function PontoPopup({ ponto, desvios, onFechar }: PontoPopupProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Detalhe do ponto ${ponto.nome}`}
      className="fixed inset-0 z-20 flex items-center justify-center bg-slate-900/70 p-4"
      onClick={onFechar}
    >
      <div
        className="w-full max-w-md rounded-[10px] border border-gray-200 bg-white p-4"
        onClick={(evento) => evento.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{ponto.nome}</h3>
          <button
            type="button"
            className="cursor-pointer rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
            onClick={onFechar}
          >
            Fechar
          </button>
        </div>

        <p className="mb-3 inline-block rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
          {ROTULO_FONTE[ponto.fonte]}
        </p>

        <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
          {(
            [
              ["TBS", `${formatarNumero(ponto.tbs, 2)} °C`],
              ["Umidade absoluta", `${formatarNumero(ponto.wKgKg * 1000, 2)} g/kg`],
              ["UR", `${formatarNumero(ponto.ur, 2)} %`],
              ["Entalpia", `${formatarNumero(ponto.entalpia, 2)} kJ/kg`],
              ["TBU", `${formatarNumero(ponto.tbu, 2)} °C`],
              ["Ponto de orvalho", `${formatarNumero(ponto.pontoOrvalho, 2)} °C`],
              ["Volume específico", `${formatarNumero(ponto.volumeEspecifico, 3)} m³/kg`],
            ] as const
          ).map(([rotulo, valor]) => (
            <div key={rotulo} className="col-span-2 grid grid-cols-subgrid">
              <dt className="text-slate-600">{rotulo}</dt>
              <dd className="text-right tabular-nums">{valor}</dd>
            </div>
          ))}
        </dl>

        {desvios.length > 0 && (
          <>
            <h4 className="mb-2 text-sm font-semibold">Conferência com o painel</h4>
            <ul className="space-y-2">
              {desvios.map((desvio) => (
                <li
                  key={desvio.campo}
                  className="rounded-md border border-gray-200 bg-slate-50 p-2 text-[12px]"
                >
                  <div className="mb-1 font-semibold">
                    {desvio.campo.toUpperCase()} · {desvio.propriedade}
                  </div>
                  <div className="flex justify-between">
                    <span>Lido/digitado</span>
                    <span className="tabular-nums">
                      {formatarNumero(desvio.medido, 2)} {desvio.unidade}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Calculado</span>
                    <span className="tabular-nums">
                      {formatarNumero(desvio.calculado, 2)} {desvio.unidade}
                    </span>
                  </div>
                  <div
                    className={`flex justify-between font-semibold ${
                      Math.abs(desvio.diferenca) > 1 ? "text-amber-700" : "text-slate-600"
                    }`}
                  >
                    <span>Diferença</span>
                    <span className="tabular-nums">
                      {desvio.diferenca > 0 ? "+" : ""}
                      {formatarNumero(desvio.diferenca, 2)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
