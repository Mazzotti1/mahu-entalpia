import { Panel } from "@/components/ui/Panel";
import { formatarNumero } from "@/lib/format";
import {
  calcTbu,
  calcularEntalpia,
  pontoOrvalhoDePressaoVapor,
  pressaoVaporDeW,
  volumeEspecifico,
  wParaUr,
} from "@/lib/psicrometria";
import { useChartStore } from "@/store/useChartStore";
import type { ProbeState } from "@/types/chart";

interface Leitura {
  rotulo: string;
  valor: string;
}

/** Propriedades do estado sob o cursor, calculadas localmente para acompanhar o mouse. */
function lerEstado({ tbs, wKgKg }: ProbeState): Leitura[] {
  const pressaoVapor = pressaoVaporDeW(wKgKg);
  return [
    { rotulo: "Bulbo seco", valor: `${formatarNumero(tbs, 2)} °C` },
    { rotulo: "Umidade relativa", valor: `${formatarNumero(wParaUr(wKgKg, tbs), 2)} %` },
    { rotulo: "Umidade absoluta", valor: `${formatarNumero(wKgKg * 1000, 4)} g/kg` },
    { rotulo: "Pressão de vapor", valor: `${formatarNumero(pressaoVapor / 1000, 4)} kPa` },
    {
      rotulo: "Volume específico",
      valor: `${formatarNumero(volumeEspecifico(tbs, wKgKg), 4)} m³/kg`,
    },
    { rotulo: "Entalpia", valor: `${formatarNumero(calcularEntalpia(tbs, wKgKg), 4)} kJ/kg` },
    {
      rotulo: "Ponto de orvalho",
      valor: `${formatarNumero(pontoOrvalhoDePressaoVapor(pressaoVapor), 2)} °C`,
    },
    { rotulo: "Bulbo úmido", valor: `${formatarNumero(calcTbu(tbs, wKgKg), 2)} °C` },
  ];
}

export function IndicatorPanel() {
  const probe = useChartStore((state) => state.probe);
  const erro = useChartStore((state) => state.erro);
  const carregando = useChartStore((state) => state.carregando);

  return (
    <Panel title="Indicador">
      {erro ? (
        <p className="text-[13px] leading-relaxed text-rose-700">
          Erro de integração com backend:
          <br />
          {erro}
        </p>
      ) : !probe ? (
        <p className="text-[13px] text-slate-600">
          {carregando ? "Calculando os pontos na API..." : "Passe o cursor sobre a carta."}
        </p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px] leading-snug">
          {lerEstado(probe).map((leitura) => (
            <div key={leitura.rotulo} className="col-span-2 grid grid-cols-subgrid">
              <dt className="text-slate-600">{leitura.rotulo}</dt>
              <dd className="text-right tabular-nums">{leitura.valor}</dd>
            </div>
          ))}
        </dl>
      )}
    </Panel>
  );
}
