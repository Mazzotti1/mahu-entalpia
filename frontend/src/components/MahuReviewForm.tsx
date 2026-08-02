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
    return campo.motivo ?? "não lido";
  }
  const confianca = formatarConfianca(campo.confidence);
  if (campo.status === "ok") {
    return `ok ${confianca}`;
  }
  // O backend diz por que duvidou (confiança baixa, pouca concordância, fora da faixa de
  // operação). Repassar o motivo evita o "confira" genérico, que não diz o que olhar.
  return campo.motivo ? `${campo.motivo} · ${confianca}` : `confira ${confianca}`;
}

interface MahuReviewFormProps {
  leitura: MahuLeituraResponse;
}

/**
 * Conferência da leitura de OCR. Aparece em TODA leitura, inclusive nas que saíram
 * inteiramente confiáveis — ver `useMahuStore.lerImagem`. Só os campos obrigatórios são
 * editáveis: os informativos (`PID UMD ABS PV`, `PID TT04 ENTALPIA PV`) não entram no
 * cálculo dos pontos.
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

  // O caminho feliz não pode parecer um pedido de correção: quando nada está duvidoso, o
  // formulário existe só para o usuário bater o olho e aceitar.
  const tudoConfiavel = leitura.missing_keys.length === 0 && !leitura.requires_review;

  // Um aviso cruzado acusa campos que, isolados, passaram no OCR: sem destacá-los aqui o
  // usuário leria "os valores não fecham" sem saber onde olhar.
  const camposComAviso = new Set(leitura.avisos.flatMap((aviso) => aviso.campos));

  return (
    <form onSubmit={handleSubmit} className="mt-3 border-t border-gray-200 pt-3">
      <h3 className="mb-2 text-sm font-semibold">Confira os valores lidos</h3>

      <p
        className={`mb-2 rounded-md border px-2 py-1.5 text-[12px] ${
          tudoConfiavel
            ? "border-emerald-300 bg-emerald-50 text-emerald-800"
            : "border-amber-400 bg-amber-50 text-amber-900"
        }`}
      >
        {tudoConfiavel
          ? "Todos os campos foram lidos com confiança. Confira e aceite."
          : "Há campos duvidosos, destacados abaixo. Corrija antes de aplicar."}
      </p>

      {leitura.avisos.length > 0 && (
        <ul className="mb-2 space-y-1">
          {leitura.avisos.map((aviso) => (
            <li
              key={`${aviso.codigo}-${aviso.campos.join("-")}`}
              className="rounded-md border border-rose-300 bg-rose-50 px-2 py-1.5 text-[12px] text-rose-900"
            >
              {aviso.mensagem}
            </li>
          ))}
        </ul>
      )}

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
            // O fluxo inteiro acontece no celular, logo após a foto: teclado numérico.
            inputMode="decimal"
            value={valores[campo.key] ?? ""}
            required={campo.obrigatorio}
            disabled={!campo.obrigatorio}
            onChange={(event) =>
              setValores((atual) => ({ ...atual, [campo.key]: event.target.value }))
            }
            className={`w-full rounded-md border px-1.5 py-1 text-right disabled:bg-slate-100 disabled:text-slate-500 ${
              camposComAviso.has(campo.key)
                ? "border-rose-600 bg-rose-50"
                : ESTILO_INPUT[campo.status]
            }`}
          />
          <span
            className={`col-span-full text-[11px] ${
              camposComAviso.has(campo.key) ? "text-rose-700" : ESTILO_BADGE[campo.status]
            }`}
          >
            {descreverStatus(campo)}
          </span>
        </label>
      ))}

      {erro && <p className="mt-1 text-[12px] text-rose-700">{erro}</p>}

      <ActionButton type="submit" className="mt-2 w-full" disabled={aplicando}>
        {aplicando ? "Aplicando..." : tudoConfiavel ? "Aceitar e aplicar" : "Aplicar à carta"}
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
