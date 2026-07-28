import { useEffect } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { Panel } from "@/components/ui/Panel";
import { formatarNumero } from "@/lib/format";
import { useHistoricoStore } from "@/store/useHistoricoStore";
import type { SimulacaoResumo } from "@/types/api";

const HORA = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const DATA_HORA = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** Leituras de hoje mostram só a hora; as anteriores levam a data junto. */
function formatarQuando(iso: string): string {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) {
    return "—";
  }
  const hoje = new Date();
  const mesmoDia =
    data.getFullYear() === hoje.getFullYear() &&
    data.getMonth() === hoje.getMonth() &&
    data.getDate() === hoje.getDate();
  return mesmoDia ? HORA.format(data) : DATA_HORA.format(data);
}

function resumirPonto(item: SimulacaoResumo): string {
  if (item.p1_tbs == null || item.p1_ur == null) {
    return `${item.total_pontos} pontos`;
  }
  return `P1 ${formatarNumero(item.p1_tbs, 1)} °C · ${formatarNumero(item.p1_ur, 0)} %`;
}

export function HistoryPanel() {
  const itens = useHistoricoStore((state) => state.itens);
  const total = useHistoricoStore((state) => state.total);
  const selecionadaId = useHistoricoStore((state) => state.selecionadaId);
  const seguindoUltima = useHistoricoStore((state) => state.seguindoUltima);
  const erro = useHistoricoStore((state) => state.erro);
  const selecionar = useHistoricoStore((state) => state.selecionar);
  const voltarASeguir = useHistoricoStore((state) => state.voltarASeguir);
  const transporte = useHistoricoStore((state) => state.transporte);
  const bootstrap = useHistoricoStore((state) => state.bootstrap);
  const observarLeituras = useHistoricoStore((state) => state.observarLeituras);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => observarLeituras(), [observarLeituras]);

  return (
    <Panel title="Leituras">
      {seguindoUltima ? (
        <p className="mb-2 flex items-center gap-1.5 text-xs text-slate-600">
          <span
            className={`inline-block size-2 shrink-0 rounded-full ${
              transporte === "sse"
                ? "bg-emerald-500"
                : transporte === "polling"
                  ? "bg-amber-500"
                  : "bg-slate-400"
            }`}
            title={
              transporte === "sse"
                ? "Conectado ao stream em tempo real"
                : transporte === "polling"
                  ? "Stream indisponível: consultando a cada 4 s"
                  : "Conectando..."
            }
          />
          Acompanhando a leitura mais recente
        </p>
      ) : (
        <ActionButton variante="ghost" className="mb-2 w-full" onClick={() => void voltarASeguir()}>
          Voltar para a mais recente
        </ActionButton>
      )}

      {erro && <p className="mb-2 text-xs text-rose-700">{erro}</p>}

      {itens.length === 0 ? (
        <p className="text-xs text-slate-500">Nenhuma leitura ainda.</p>
      ) : (
        <ul className="-mx-1 max-h-64 overflow-y-auto">
          {itens.map((item) => {
            const ativa = item.id === selecionadaId;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => void selecionar(item.id)}
                  aria-current={ativa ? "true" : undefined}
                  className={`w-full cursor-pointer rounded-md px-2 py-1.5 text-left text-[13px] ${
                    ativa ? "bg-blue-50 ring-1 ring-blue-400" : "hover:bg-slate-50"
                  }`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-medium tabular-nums">{formatarQuando(item.criado_em)}</span>
                    <span className="text-[11px] text-slate-500 tabular-nums">#{item.id}</span>
                  </span>
                  <span className="block truncate text-[11px] text-slate-500">
                    {resumirPonto(item)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {total > itens.length && (
        <p className="mt-2 text-[11px] text-slate-500">
          Mostrando as {itens.length} mais recentes de {total}.
        </p>
      )}
    </Panel>
  );
}
