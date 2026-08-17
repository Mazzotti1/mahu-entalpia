import { useEffect, useState, type KeyboardEvent } from "react";

/**
 * O campo PID TT04 ENTALPIA (SP), digitável individualmente em cada carta.
 *
 * É o único campo do painel que a planta PERSEGUE em vez de medir, e por isso o único que
 * faz sentido digitar sem uma foto por trás. Cada carta tem o seu, e eles querem dizer
 * coisas diferentes:
 *
 * - na CARTA ATUAL é o SP que a planta está de fato usando. Acompanha a leitura até o
 *   backend e volta como desvio contra a entalpia calculada. Não move os pontos: nessa carta
 *   nenhum ponto vem de setpoint.
 * - na CARTA CALCULADA é um alvo hipotético. Muda a cadeia inteira daquela carta, sem gravar
 *   nada em `/setpoints` — a configuração da planta continua sendo a de lá.
 *
 * Confirma no Enter ou ao sair do campo, e não a cada tecla: na carta calculada cada
 * confirmação é uma requisição, e digitar "36,20" dispararia cinco.
 */
interface EntalpiaSpInputProps {
  valor: number | null;
  aoConfirmar: (valor: number | null) => void;
  ajuda: string;
}

export function EntalpiaSpInput({ valor, aoConfirmar, ajuda }: EntalpiaSpInputProps) {
  const [rascunho, setRascunho] = useState(valor?.toString() ?? "");

  // Quem manda é o valor de fora: uma leitura aplicada traz o SP lido na foto, e o campo
  // precisa passar a mostrá-lo.
  useEffect(() => {
    setRascunho(valor?.toString() ?? "");
  }, [valor]);

  const confirmar = () => {
    const bruto = rascunho.trim();
    if (bruto === "") {
      aoConfirmar(null);
      return;
    }
    // Vírgula decimal: é o que o painel escreve e o que o teclado pt-BR oferece.
    const numero = Number(bruto.replace(",", "."));
    if (Number.isFinite(numero)) {
      aoConfirmar(numero);
    } else {
      // Entrada impossível volta ao último valor bom em vez de virar `null` silencioso.
      setRascunho(valor?.toString() ?? "");
    }
  };

  const aoTeclar = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
    }
  };

  return (
    <label className="mb-1 flex items-center gap-2 text-[12px] text-slate-600 paisagem:hidden">
      <span className="shrink-0">PID TT04 ENTALPIA (SP)</span>
      <input
        type="text"
        inputMode="decimal"
        value={rascunho}
        placeholder="—"
        onChange={(event) => setRascunho(event.target.value)}
        onBlur={confirmar}
        onKeyDown={aoTeclar}
        title={ajuda}
        className="w-[86px] rounded-md border border-slate-300 px-1.5 py-0.5 text-right"
      />
      <span className="shrink-0">kJ/kg</span>
    </label>
  );
}
