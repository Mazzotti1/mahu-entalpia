import { useState, type FormEvent } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { formatarConfianca } from "@/lib/format";
import { useMahuStore } from "@/store/useMahuStore";
import type { MahuCampoOCR, MahuCampoStatus, MahuLeituraResponse } from "@/types/api";

const ESTILO_INPUT: Record<MahuCampoStatus, string> = {
  ok: "border-slate-300",
  low_confidence: "border-amber-500 bg-amber-50",
  unreadable: "border-rose-600 bg-rose-50",
};

const ESTILO_BADGE: Record<MahuCampoStatus, string> = {
  ok: "text-slate-500",
  low_confidence: "text-amber-700",
  unreadable: "text-rose-700",
};

function descreverStatus(campo: MahuCampoOCR): string {
  if (campo.pv == null) {
    return "não lido";
  }
  const confianca = formatarConfianca(campo.confidence);
  return campo.status === "ok" ? `ok ${confianca}` : `confira ${confianca}`;
}

interface MahuReviewFormProps {
  leitura: MahuLeituraResponse;
}

/**
 * Conferência manual da leitura de OCR. Só os campos obrigatórios são editáveis: os
 * informativos (`PID UMD ABS PV`, `PID TT04 ENTALPIA PV`) não entram no cálculo dos pontos.
 *
 * O componente é remontado a cada leitura (via `key` no pai), então o estado inicial
 * vindo do OCR não precisa de sincronização por efeito.
 */
export function MahuReviewForm({ leitura }: MahuReviewFormProps) {
  const aplicarConferencia = useMahuStore((state) => state.aplicarConferencia);
  const descartarLeitura = useMahuStore((state) => state.descartarLeitura);
  const aplicando = useMahuStore((state) => state.aplicando);

  const [valores, setValores] = useState<Record<string, string>>(() =>
    Object.fromEntries(leitura.campos.map((campo) => [campo.key, campo.pv?.toString() ?? ""])),
  );
  const [erro, setErro] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const numericos: Record<string, number> = {};
    for (const campo of leitura.campos) {
      if (!campo.obrigatorio) {
        continue;
      }
      const bruto = valores[campo.key]?.trim() ?? "";
      const numero = Number(bruto);
      if (bruto === "" || Number.isNaN(numero)) {
        setErro(`Preencha um valor numérico para ${campo.label}.`);
        return;
      }
      numericos[campo.key] = numero;
    }

    setErro(null);
    void aplicarConferencia(numericos);
  };

  return (
    <form onSubmit={handleSubmit} className="mt-3 border-t border-gray-200 pt-3">
      <h3 className="mb-2 text-sm font-semibold">Confira os valores lidos</h3>

      {leitura.campos.map((campo) => (
        <label
          key={campo.key}
          className="grid grid-cols-[1fr_82px] items-center gap-x-2 gap-y-0.5 py-1.5 text-[13px]"
        >
          <span className="min-w-0">
            {campo.label} ({campo.unidade})
          </span>
          <input
            type="number"
            step="0.01"
            value={valores[campo.key] ?? ""}
            required={campo.obrigatorio}
            disabled={!campo.obrigatorio}
            onChange={(event) =>
              setValores((atual) => ({ ...atual, [campo.key]: event.target.value }))
            }
            className={`w-full rounded-md border px-1.5 py-1 text-right disabled:bg-slate-100 disabled:text-slate-500 ${ESTILO_INPUT[campo.status]}`}
          />
          <span className={`col-span-full text-[11px] ${ESTILO_BADGE[campo.status]}`}>
            {descreverStatus(campo)}
          </span>
        </label>
      ))}

      {erro && <p className="mt-1 text-[12px] text-rose-700">{erro}</p>}

      <ActionButton type="submit" className="mt-2 w-full" disabled={aplicando}>
        {aplicando ? "Aplicando..." : "Aplicar à carta"}
      </ActionButton>
      <ActionButton
        variante="ghost"
        className="mt-2 w-full"
        onClick={descartarLeitura}
        disabled={aplicando}
      >
        Descartar leitura
      </ActionButton>
    </form>
  );
}
