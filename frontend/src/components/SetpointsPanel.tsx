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
  // `entalpia_alvo_seco` saiu daqui: era o alvo que a antiga estratégia por região escolhia
  // para o ar seco, e a carta otimizada não escolhe mais entre alvos de tabela — ela deduz o
  // ótimo (ver `otimizacao.py`). A coluna continua no banco porque as migrações são
  // append-only; nenhum cálculo a lê, e um campo editável que não muda nada é pior que
  // nenhum campo.
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
 * Tarifas: não entram em cálculo psicrométrico nenhum, só convertem kW em reais.
 *
 * Separadas dos setpoints na tela porque respondem a outra pergunta. Setpoint errado move
 * os pontos da carta; tarifa errada não move nada — só faz a comparação entre as duas cartas
 * apontar para a economia errada. Quem confere uma não está conferindo a outra.
 */
const TARIFAS: CampoSetpoint[] = [
  { chave: "preco_kwh", rotulo: "Preço da energia", unidade: "R$/kWh", passo: "0.01" },
  {
    chave: "cop_refrigeracao",
    rotulo: "COP do chiller",
    unidade: "kW térmico / kW elétrico",
    passo: "0.1",
    ajuda: "Quantos kW de calor o chiller remove por kW elétrico consumido.",
  },
  {
    chave: "rendimento_aquecimento",
    rotulo: "Rendimento do aquecimento",
    unidade: "0 a 1",
    passo: "0.01",
    ajuda: "Resistência elétrica fica perto de 1. Caldeira, bem abaixo.",
  },
  { chave: "preco_agua_m3", rotulo: "Preço da água", unidade: "R$/m³", passo: "0.01" },
];

const TODOS_OS_CAMPOS = [...CAMPOS, ...TARIFAS];

/** Uma linha do formulário. `type="text"` pelo mesmo motivo da conferência do MAHU: com
 * `number` a vírgula decimal esvazia o campo em silêncio. */
function Campo({
  campo,
  valor,
  aoMudar,
}: {
  campo: CampoSetpoint;
  valor: string;
  aoMudar: (valor: string) => void;
}) {
  return (
    <label className="mb-2 block text-[13px]">
      <span className="mb-0.5 block">
        {campo.rotulo} <span className="text-slate-500">({campo.unidade})</span>
      </span>
      <input
        type="text"
        inputMode="decimal"
        value={valor}
        onChange={(event) => aoMudar(event.target.value)}
        className="w-full rounded-md border border-slate-300 px-1.5 py-1 text-right"
      />
      {campo.ajuda && (
        <span className="mt-0.5 block text-[11px] text-slate-500">{campo.ajuda}</span>
      )}
    </label>
  );
}

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
      Object.fromEntries(
        TODOS_OS_CAMPOS.map(({ chave }) => [chave, String(setpoints[chave])]),
      ),
    );
  }, [setpoints]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valores: Record<string, number> = {};
    for (const { chave, rotulo } of TODOS_OS_CAMPOS) {
      // Vírgula decimal aceita: é o que o teclado pt-BR oferece, e `Number("0,75")` é NaN.
      const numero = Number(String(rascunho[chave] ?? "").replace(",", "."));
      if (!Number.isFinite(numero)) {
        setErro(`Informe um número para ${rotulo}.`);
        return;
      }
      valores[chave] = numero;
    }
    // `entalpia_alvo_seco` não tem mais campo na tela, mas o PUT substitui a linha inteira:
    // sem repassar o valor vigente, ele voltaria ao default do modelo a cada gravação.
    valores.entalpia_alvo_seco = setpoints.entalpia_alvo_seco;

    setErro(null);
    try {
      await atualizarSetpoints(valores as unknown as Setpoints);
    } catch {
      setErro("O servidor recusou estes setpoints. Confira as unidades.");
    }
  };

  const alterado = TODOS_OS_CAMPOS.some(
    ({ chave }) => Number(String(rascunho[chave] ?? "").replace(",", ".")) !== setpoints[chave],
  );

  return (
    <Panel title="Setpoints">
      <form onSubmit={handleSubmit} noValidate>
        {CAMPOS.map((campo) => (
          <Campo
            key={campo.chave}
            campo={campo}
            valor={rascunho[campo.chave] ?? ""}
            aoMudar={(valor) =>
              setRascunho((atual) => ({ ...atual, [campo.chave]: valor }))
            }
          />
        ))}

        <h3 className="mt-3 mb-1.5 border-t border-gray-200 pt-2.5 text-[13px] font-semibold">
          Tarifas
        </h3>
        <p className="mb-2 text-[11px] text-slate-500">
          Não mexem na carta. Convertem o gasto térmico em reais, que é o que a comparação
          entre a Carta Atual e a Otimizada usa.
        </p>
        {TARIFAS.map((campo) => (
          <Campo
            key={campo.chave}
            campo={campo}
            valor={rascunho[campo.chave] ?? ""}
            aoMudar={(valor) =>
              setRascunho((atual) => ({ ...atual, [campo.chave]: valor }))
            }
          />
        ))}

        {erro && <p className="mb-1 text-[12px] text-rose-700">{erro}</p>}

        <ActionButton type="submit" className="w-full" disabled={salvando || !alterado}>
          {salvando ? "Salvando..." : "Salvar e recalcular"}
        </ActionButton>
      </form>
    </Panel>
  );
}
