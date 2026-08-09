import { useEffect, useMemo, useState } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { describeError } from "@/lib/http";
import { formatarNumero } from "@/lib/format";
import { buscarHistoricoGastoTermico } from "@/services/psicrometriaApi";
import type { GastoTermicoHistoricoItem } from "@/types/api";

const LARGURA = 640;
const ALTURA = 320;
const MARGEM = { esquerda: 56, direita: 16, topo: 16, baixo: 40 };

interface Escala {
  min: number;
  max: number;
  paraPixel: (valor: number) => number;
}

/** Domínio com folga de 10% para os pontos não caírem em cima do eixo. */
function escala(valores: number[], tamanhoPx: number, inverter: boolean): Escala {
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const folga = (max - min || 1) * 0.1;
  const domMin = min - folga;
  const domMax = max + folga;
  return {
    min: domMin,
    max: domMax,
    paraPixel: (valor) => {
      const fracao = (valor - domMin) / (domMax - domMin);
      return inverter ? tamanhoPx - fracao * tamanhoPx : fracao * tamanhoPx;
    },
  };
}

function paraCsv(itens: GastoTermicoHistoricoItem[]): string {
  const cabecalho = "Data;Gasto termico (kW);Delta H (kJ/kg)";
  const linhas = itens.map((item) =>
    [
      item.criado_em,
      formatarNumero(item.gasto_termico_kw, 2),
      item.delta_h_entalpia == null ? "" : formatarNumero(item.delta_h_entalpia, 2),
    ].join(";"),
  );
  // BOM na frente: sem ele o Excel em pt-BR interpreta o UTF-8 como Latin-1 e estraga os
  // acentos do cabeçalho.
  return `﻿${[cabecalho, ...linhas].join("\r\n")}`;
}

function exportarCsv(itens: GastoTermicoHistoricoItem[]): void {
  const blob = new Blob([paraCsv(itens)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "gasto_termico_delta_h.csv";
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Gasto térmico × Delta H de cada leitura, para achar se o consumo sobe quando o painel se
 * afasta do setpoint de entalpia. Delta H = entalpia do setpoint de P2 − entalpia
 * lida/digitada no PID TT04 ENTALPIA (PV); leituras sem esse campo ficam de fora do gráfico
 * mas continuam na planilha exportada.
 */
export function GastoTermicoChart() {
  const [itens, setItens] = useState<GastoTermicoHistoricoItem[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    setCarregando(true);
    buscarHistoricoGastoTermico()
      .then((resposta) => {
        if (!cancelado) {
          setItens(resposta.itens);
          setErro(null);
        }
      })
      .catch((error: unknown) => {
        if (!cancelado) {
          setErro(describeError(error));
        }
      })
      .finally(() => {
        if (!cancelado) {
          setCarregando(false);
        }
      });
    return () => {
      cancelado = true;
    };
  }, []);

  const pontosValidos = useMemo(
    () => itens.filter((item): item is GastoTermicoHistoricoItem & { delta_h_entalpia: number } =>
      item.delta_h_entalpia != null,
    ),
    [itens],
  );

  const escalas = useMemo(() => {
    if (pontosValidos.length === 0) {
      return null;
    }
    const larguraUtil = LARGURA - MARGEM.esquerda - MARGEM.direita;
    const alturaUtil = ALTURA - MARGEM.topo - MARGEM.baixo;
    return {
      x: escala(
        pontosValidos.map((item) => item.delta_h_entalpia),
        larguraUtil,
        false,
      ),
      y: escala(
        pontosValidos.map((item) => item.gasto_termico_kw),
        alturaUtil,
        true,
      ),
    };
  }, [pontosValidos]);

  return (
    <section className="mt-4 max-w-[1200px] rounded-[10px] border border-gray-200 bg-white p-3 paisagem:hidden">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">Gasto térmico × Delta H</h3>
        <ActionButton
          variante="ghost"
          className="px-3 py-1.5 text-xs"
          disabled={itens.length === 0}
          onClick={() => exportarCsv(itens)}
        >
          Exportar planilha (CSV)
        </ActionButton>
      </div>

      {carregando ? (
        <p className="text-[13px] text-slate-600">Carregando histórico...</p>
      ) : erro ? (
        <p className="text-[13px] text-rose-700">Erro ao carregar histórico: {erro}</p>
      ) : pontosValidos.length === 0 ? (
        <p className="text-[13px] text-slate-600">
          Nenhuma leitura com PID TT04 ENTALPIA (PV) informado ainda — o gráfico aparece
          assim que houver Delta H para comparar.
        </p>
      ) : (
        <svg
          viewBox={`0 0 ${LARGURA} ${ALTURA}`}
          className="w-full"
          role="img"
          aria-label="Dispersão de gasto térmico por Delta H"
        >
          <g transform={`translate(${MARGEM.esquerda},${MARGEM.topo})`}>
            {/* Eixos */}
            <line
              x1={0}
              y1={ALTURA - MARGEM.topo - MARGEM.baixo}
              x2={LARGURA - MARGEM.esquerda - MARGEM.direita}
              y2={ALTURA - MARGEM.topo - MARGEM.baixo}
              stroke="#cbd5e1"
            />
            <line
              x1={0}
              y1={0}
              x2={0}
              y2={ALTURA - MARGEM.topo - MARGEM.baixo}
              stroke="#cbd5e1"
            />

            {escalas &&
              pontosValidos.map((item) => (
                <circle
                  key={item.processo_id}
                  cx={escalas.x.paraPixel(item.delta_h_entalpia)}
                  cy={escalas.y.paraPixel(item.gasto_termico_kw)}
                  r={4}
                  fill="#1d4ed8"
                  fillOpacity={0.75}
                >
                  <title>
                    {`${item.criado_em}\nGasto térmico: ${formatarNumero(item.gasto_termico_kw, 2)} kW\nDelta H: ${formatarNumero(item.delta_h_entalpia, 2)} kJ/kg`}
                  </title>
                </circle>
              ))}
          </g>

          {/* Rótulos dos eixos */}
          <text
            x={LARGURA / 2}
            y={ALTURA - 6}
            textAnchor="middle"
            className="fill-slate-600 text-[11px]"
          >
            Delta H (kJ/kg) — entalpia do setpoint menos a do PID TT04 ENTALPIA (PV)
          </text>
          <text
            x={14}
            y={ALTURA / 2}
            textAnchor="middle"
            transform={`rotate(-90 14 ${ALTURA / 2})`}
            className="fill-slate-600 text-[11px]"
          >
            Gasto térmico (kW)
          </text>
        </svg>
      )}
    </section>
  );
}
