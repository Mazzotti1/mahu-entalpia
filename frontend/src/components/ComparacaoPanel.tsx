import { formatarNumero } from "@/lib/format";
import type { ProcessoResponse } from "@/types/api";

/**
 * As duas cartas confrontadas: o que a planta está gastando contra o que ela gastaria pela
 * rota mais barata, e ponto a ponto onde as duas se separam.
 *
 * Duas tabelas porque são duas perguntas diferentes. A primeira responde "quanto", em kW e
 * em reais, e é a que decide se vale mexer na planta. A segunda responde "onde": qual ponto
 * do MAHU está fora do lugar, que é o que diz O QUE mexer. Juntar as duas numa só faria a
 * linha do dinheiro competir por atenção com a linha da temperatura.
 */
interface ComparacaoPanelProps {
  atual: ProcessoResponse | null;
  otimizado: ProcessoResponse | null;
}

/** Uma linha da tabela de gastos. `melhorEhMenor` decide de que lado fica a economia. */
interface LinhaGasto {
  rotulo: string;
  unidade: string;
  casas: number;
  atual: number;
  otimizado: number;
  /** Destaca a linha: são as que respondem "quanto custa" em vez de "quanto consome". */
  destaque?: boolean;
}

function economiaPercentual(atual: number, otimizado: number): string {
  if (atual === 0) {
    return "—";
  }
  return `${formatarNumero(((atual - otimizado) / atual) * 100, 1)}%`;
}

function TabelaGastos({ linhas }: { linhas: LinhaGasto[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="border border-gray-200 p-2 text-left font-semibold">Grandeza</th>
            <th className="border border-gray-200 p-2 text-center font-semibold">
              CARTA ATUAL
            </th>
            <th className="border border-gray-200 p-2 text-center font-semibold">
              CARTA OTIMIZADA
            </th>
            <th className="border border-gray-200 p-2 text-center font-semibold">Economia</th>
            <th className="border border-gray-200 p-2 text-center font-semibold">%</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha) => {
            const economia = linha.atual - linha.otimizado;
            return (
              <tr key={linha.rotulo} className={linha.destaque ? "bg-emerald-50/60" : ""}>
                <td
                  className={`border border-gray-200 p-2 ${
                    linha.destaque ? "font-semibold" : ""
                  }`}
                >
                  {linha.rotulo}{" "}
                  <span className="text-[11px] font-normal text-slate-500">
                    ({linha.unidade})
                  </span>
                </td>
                <td className="border border-gray-200 p-2 text-center tabular-nums">
                  {formatarNumero(linha.atual, linha.casas)}
                </td>
                <td className="border border-gray-200 p-2 text-center tabular-nums">
                  {formatarNumero(linha.otimizado, linha.casas)}
                </td>
                <td
                  className={`border border-gray-200 p-2 text-center font-semibold tabular-nums ${
                    // Economia negativa quer dizer que a rota "ótima" gasta MAIS naquela
                    // grandeza. Acontece de verdade: trocar reaquecimento por resfriamento
                    // move gasto de uma serpentina para a outra, e só a linha do dinheiro
                    // decide se a troca compensou.
                    economia > 0 ? "text-emerald-700" : economia < 0 ? "text-rose-700" : ""
                  }`}
                >
                  {economia > 0 ? "−" : economia < 0 ? "+" : ""}
                  {formatarNumero(Math.abs(economia), linha.casas)}
                </td>
                <td className="border border-gray-200 p-2 text-center tabular-nums">
                  {economiaPercentual(linha.atual, linha.otimizado)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const GRANDEZAS_DOS_PONTOS = [
  { rotulo: "TBS (°C)", casas: 2, ler: (p: ProcessoResponse["pontos"][number]) => p.tbs },
  { rotulo: "W (g/kg)", casas: 2, ler: (p: ProcessoResponse["pontos"][number]) => p.w },
  { rotulo: "UR (%)", casas: 1, ler: (p: ProcessoResponse["pontos"][number]) => p.ur },
  {
    rotulo: "h (kJ/kg)",
    casas: 2,
    ler: (p: ProcessoResponse["pontos"][number]) => p.entalpia,
  },
] as const;

function TabelaPontos({
  atual,
  otimizado,
}: {
  atual: ProcessoResponse;
  otimizado: ProcessoResponse;
}) {
  // As duas cadeias usam os MESMOS rótulos (nomes dos campos do painel), e é isso que
  // permite casar linha a linha. Um ponto que só exista de um lado — TT_02 ausente da
  // leitura, por exemplo — aparece com traço em vez de sumir da tabela.
  const rotulos = [...new Set([...atual.pontos, ...otimizado.pontos].map((p) => p.label))];
  const porLabelAtual = new Map(atual.pontos.map((p) => [p.label, p]));
  const porLabelOtimizado = new Map(otimizado.pontos.map((p) => [p.label, p]));

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th rowSpan={2} className="border border-gray-200 p-2 font-semibold">
              Ponto
            </th>
            {GRANDEZAS_DOS_PONTOS.map((grandeza) => (
              <th
                key={grandeza.rotulo}
                colSpan={2}
                className="border border-gray-200 p-2 text-center font-semibold"
              >
                {grandeza.rotulo}
              </th>
            ))}
          </tr>
          <tr>
            {GRANDEZAS_DOS_PONTOS.map((grandeza) => [
              <th
                key={`${grandeza.rotulo}-atual`}
                className="border border-gray-200 px-2 py-1 text-center text-[11px] font-normal text-slate-500"
              >
                atual
              </th>,
              <th
                key={`${grandeza.rotulo}-otimo`}
                className="border border-gray-200 px-2 py-1 text-center text-[11px] font-normal text-slate-500"
              >
                otimizada
              </th>,
            ])}
          </tr>
        </thead>
        <tbody>
          {rotulos.map((rotulo) => {
            const pontoAtual = porLabelAtual.get(rotulo);
            const pontoOtimo = porLabelOtimizado.get(rotulo);
            return (
              <tr key={rotulo}>
                <td className="border border-gray-200 p-2 text-center font-semibold">
                  {rotulo}
                </td>
                {GRANDEZAS_DOS_PONTOS.map((grandeza) => {
                  const valorAtual = pontoAtual ? grandeza.ler(pontoAtual) : null;
                  const valorOtimo = pontoOtimo ? grandeza.ler(pontoOtimo) : null;
                  // Diferença acima de meia unidade é o que vale destacar: abaixo disso é
                  // arredondamento do painel, não decisão de operação.
                  const divergente =
                    valorAtual != null &&
                    valorOtimo != null &&
                    Math.abs(valorAtual - valorOtimo) >= 0.5;
                  return [
                    <td
                      key={`${rotulo}-${grandeza.rotulo}-atual`}
                      className={`border border-gray-200 p-2 text-center tabular-nums ${
                        divergente ? "font-semibold text-rose-700" : ""
                      }`}
                    >
                      {valorAtual == null ? "—" : formatarNumero(valorAtual, grandeza.casas)}
                    </td>,
                    <td
                      key={`${rotulo}-${grandeza.rotulo}-otimo`}
                      className={`border border-gray-200 p-2 text-center tabular-nums ${
                        divergente ? "font-semibold text-emerald-700" : ""
                      }`}
                    >
                      {valorOtimo == null ? "—" : formatarNumero(valorOtimo, grandeza.casas)}
                    </td>,
                  ];
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ComparacaoPanel({ atual, otimizado }: ComparacaoPanelProps) {
  if (!atual || !otimizado || !atual.custo || !otimizado.custo) {
    return null;
  }

  const linhas: LinhaGasto[] = [
    {
      rotulo: "Refrigeração",
      unidade: "kW térmico",
      casas: 1,
      atual: atual.totais.q_refrigeracao_kw,
      otimizado: otimizado.totais.q_refrigeracao_kw,
    },
    {
      rotulo: "Aquecimento",
      unidade: "kW térmico",
      casas: 1,
      atual: atual.totais.q_aquecimento_kw,
      otimizado: otimizado.totais.q_aquecimento_kw,
    },
    {
      rotulo: "Água de umidificação",
      unidade: "kg/h",
      casas: 1,
      atual: atual.totais.agua_umidificacao_kg_h,
      otimizado: otimizado.totais.agua_umidificacao_kg_h,
    },
    {
      rotulo: "Condensado",
      unidade: "kg/h",
      casas: 1,
      atual: atual.totais.condensado_kg_h,
      otimizado: otimizado.totais.condensado_kg_h,
    },
    {
      rotulo: "Consumo elétrico",
      unidade: "kW",
      casas: 1,
      atual: atual.custo.energia_total_kw,
      otimizado: otimizado.custo.energia_total_kw,
      destaque: true,
    },
    {
      rotulo: "Custo",
      unidade: "R$/h",
      casas: 2,
      atual: atual.custo.reais_por_hora,
      otimizado: otimizado.custo.reais_por_hora,
      destaque: true,
    },
    {
      rotulo: "Custo",
      unidade: "R$/dia",
      casas: 2,
      atual: atual.custo.reais_por_dia,
      otimizado: otimizado.custo.reais_por_dia,
      destaque: true,
    },
    {
      rotulo: "Custo",
      unidade: "R$/mês (30 dias)",
      casas: 2,
      atual: atual.custo.reais_por_mes,
      otimizado: otimizado.custo.reais_por_mes,
      destaque: true,
    },
  ];

  const economiaMensal = atual.custo.reais_por_mes - otimizado.custo.reais_por_mes;

  return (
    <section className="mt-4 max-w-[1200px] rounded-[10px] border border-gray-200 bg-white p-3 paisagem:hidden">
      <h3 className="text-lg font-semibold">Comparação — ATUAL × OTIMIZADA</h3>
      <p className="mb-2.5 text-[12px] text-slate-500">
        A carta otimizada parte dos dois primeiros pontos medidos (TT01 e TT_02) e escolhe a
        rota mais barata até os setpoints de umidade e temperatura. A diferença abaixo é o
        que a operação atual está pagando a mais.
      </p>

      <p
        className={`mb-3 rounded-md border px-2 py-1.5 text-[13px] ${
          economiaMensal > 0
            ? "border-emerald-300 bg-emerald-50 text-emerald-900"
            : "border-slate-300 bg-slate-50 text-slate-700"
        }`}
      >
        {economiaMensal > 0
          ? `A rota otimizada economizaria R$ ${formatarNumero(economiaMensal, 2)} por mês nesta condição de ar.`
          : "A operação atual já está na rota mais barata para esta condição de ar."}
      </p>

      <h4 className="mb-1.5 text-sm font-semibold">1. Gastos</h4>
      <TabelaGastos linhas={linhas} />

      {otimizado.avisos.length > 0 && (
        <ul className="mt-2 space-y-1">
          {otimizado.avisos.map((aviso) => (
            <li
              key={aviso.codigo}
              className="rounded-md border border-amber-400 bg-amber-50 px-2 py-1.5 text-[12px] text-amber-900"
            >
              {aviso.mensagem}
              {aviso.codigo === "pre_aquecimento_pago_duas_vezes" &&
                otimizado.custo_evitavel_reais_h != null && (
                  <strong>
                    {" "}
                    São R$ {formatarNumero(otimizado.custo_evitavel_reais_h, 2)}/h — R${" "}
                    {formatarNumero(otimizado.custo_evitavel_reais_h * 24 * 30, 2)}/mês.
                  </strong>
                )}
            </li>
          ))}
        </ul>
      )}

      <h4 className="mt-4 mb-1.5 text-sm font-semibold">2. Valores dos pontos</h4>
      <p className="mb-1.5 text-[11px] text-slate-500">
        Em destaque, os pontos que divergem em meia unidade ou mais — são eles que produzem a
        diferença de custo da tabela acima.
      </p>
      <TabelaPontos atual={atual} otimizado={otimizado} />
    </section>
  );
}
