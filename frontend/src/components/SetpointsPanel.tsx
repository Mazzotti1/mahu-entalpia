import { useEffect, useState, type FormEvent } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { Panel } from "@/components/ui/Panel";
import { useProcessoStore } from "@/store/useProcessoStore";
import type { Setpoints } from "@/types/api";

interface CampoSetpoint {
  chave: keyof Setpoints;
  rotulo: string;
  unidade: string;
  passo: string;
  ajuda?: string;
}

const CAMPOS: CampoSetpoint[] = [
  { chave: "w_saida", rotulo: "Umidade abs. de saída", unidade: "g/kg", passo: "0.01" },
  { chave: "tbs_final", rotulo: "Temperatura de insuflamento", unidade: "°C", passo: "0.1" },
  { chave: "entalpia_alvo", rotulo: "Entalpia alvo (P2)", unidade: "kJ/kg", passo: "0.01" },
  { chave: "vazao_m3h", rotulo: "Vazão do MAHU", unidade: "m³/h", passo: "1" },
  {
    chave: "pressao_atm",
    rotulo: "Pressão atmosférica",
    unidade: "Pa",
    passo: "1",
    // A especificação original pedia "101325 kPa", que seriam mil atmosferas. O backend
    // recusa fora de 80.000–110.000, e dizer a unidade aqui evita a viagem até o 422.
    ajuda: "Em Pa, não kPa. Ao nível do mar são 101325.",
  },
];

/**
 * Os setpoints são da planta, não da sessão: ficam no servidor e valem para quem abrir o
 * app. Salvar recalcula o processo — mudar o alvo sem redesenhar a carta deixaria a tela
 * mostrando o resultado da configuração anterior.
 */
export function SetpointsPanel() {
  const setpoints = useProcessoStore((state) => state.setpoints);
  const carregarSetpoints = useProcessoStore((state) => state.carregarSetpoints);
  const atualizarSetpoints = useProcessoStore((state) => state.atualizarSetpoints);
  const salvando = useProcessoStore((state) => state.salvandoSetpoints);

  const [rascunho, setRascunho] = useState<Record<string, string>>({});
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    void carregarSetpoints();
  }, [carregarSetpoints]);

  // Os valores do servidor mandam; o rascunho só existe enquanto o usuário digita.
  useEffect(() => {
    setRascunho(
      Object.fromEntries(CAMPOS.map(({ chave }) => [chave, String(setpoints[chave])])),
    );
  }, [setpoints]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valores: Record<string, number> = {};
    for (const { chave, rotulo } of CAMPOS) {
      const numero = Number(rascunho[chave]);
      if (!Number.isFinite(numero)) {
        setErro(`Informe um número para ${rotulo}.`);
        return;
      }
      valores[chave] = numero;
    }
    setErro(null);
    try {
      await atualizarSetpoints(valores as unknown as Setpoints);
    } catch {
      setErro("O servidor recusou estes setpoints. Confira as unidades.");
    }
  };

  const alterado = CAMPOS.some(({ chave }) => Number(rascunho[chave]) !== setpoints[chave]);

  return (
    <Panel title="Setpoints">
      <form onSubmit={handleSubmit}>
        {CAMPOS.map(({ chave, rotulo, unidade, passo, ajuda }) => (
          <label key={chave} className="mb-2 block text-[13px]">
            <span className="mb-0.5 block">
              {rotulo} <span className="text-slate-500">({unidade})</span>
            </span>
            <input
              type="number"
              step={passo}
              inputMode="decimal"
              value={rascunho[chave] ?? ""}
              onChange={(event) =>
                setRascunho((atual) => ({ ...atual, [chave]: event.target.value }))
              }
              className="w-full rounded-md border border-slate-300 px-1.5 py-1 text-right"
            />
            {ajuda && <span className="mt-0.5 block text-[11px] text-slate-500">{ajuda}</span>}
          </label>
        ))}

        {erro && <p className="mb-1 text-[12px] text-rose-700">{erro}</p>}

        <ActionButton type="submit" className="w-full" disabled={salvando || !alterado}>
          {salvando ? "Salvando..." : "Salvar e recalcular"}
        </ActionButton>
      </form>
    </Panel>
  );
}
