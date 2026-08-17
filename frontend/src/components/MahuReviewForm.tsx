import { useState, type FormEvent } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { formatarConfianca } from "@/lib/format";
import { useMahuStore } from "@/store/useMahuStore";
import type {
  MahuCampoOCR,
  MahuCampoStatus,
  MahuLeituraResponse,
  MahuMotivoDescarte,
} from "@/types/api";

/**
 * O descarte pergunta o motivo porque é o único ponto do fluxo em que o usuário sabe algo
 * que nem o OCR nem os validadores conseguem descobrir: se a FOTO estava ruim, e como.
 * Aplicar e corrigir já rotulam o reconhecimento; nada rotulava a captura.
 *
 * `leu_errado` é separado dos três primeiros de propósito: foto boa com leitura ruim é um
 * problema de reconhecimento, e deixá-lo puxar os limiares de captura ensinaria o guia da
 * câmera a reclamar de fotos que estavam certas.
 */
const MOTIVOS: ReadonlyArray<{ valor: MahuMotivoDescarte; rotulo: string }> = [
  { valor: "borrada", rotulo: "Borrada" },
  { valor: "reflexo", rotulo: "Reflexo" },
  { valor: "cortada", rotulo: "Cortada" },
  { valor: "leu_errado", rotulo: "Leu errado" },
];

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

/**
 * Aceita vírgula decimal. O painel do MAHU escreve "20,80", o teclado do celular em pt-BR
 * oferece vírgula, e é isso que a pessoa digita ao corrigir um campo — `Number("20,80")` é
 * `NaN`, e o valor sumia sem explicação nenhuma.
 */
function paraNumero(bruto: string): number | null {
  const numero = Number(bruto.replace(",", "."));
  return Number.isFinite(numero) ? numero : null;
}

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
 * inteiramente confiáveis — ver `useMahuStore.lerImagem`.
 *
 * Todos os campos são editáveis, incluindo `PID UMD ABS PV` e `PID TT04 ENTALPIA PV`. Eles
 * eram exibidos desabilitados, e por isso nunca produziam o par sugerido/aplicado — ficavam
 * de fora do corpus e não podiam ser medidos nem afinados. A diferença que sobrou é que
 * deixá-los vazios não trava o envio: o bloco SP/PV/MV do painel tem 17 px entre linhas e
 * nem toda foto o resolve.
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
  // O primeiro toque em "Descartar" abre os motivos em vez de fechar. Um clique a mais,
  // mas é o único rótulo de foto ruim que este fluxo produz — e sem ele o corpus só
  // acumula fotos que deram certo.
  const [perguntandoMotivo, setPerguntandoMotivo] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const numericos: Record<string, number> = {};
    for (const campo of leitura.campos) {
      const bruto = valores[campo.key]?.trim() ?? "";
      const numero = paraNumero(bruto);
      if (bruto === "" || numero === null) {
        // Vazio nos campos do bloco SP/PV/MV é resultado normal: nem toda foto os resolve,
        // e o backend os aceita ausentes. Só os obrigatórios travam o envio.
        if (campo.obrigatorio) {
          setErro(
            bruto === ""
              ? `Preencha um valor numérico para ${campo.label}.`
              : `"${bruto}" não é um número válido para ${campo.label}.`,
          );
          return;
        }
        continue;
      }
      numericos[campo.key] = numero;
    }

    setErro(null);
    // A falha volta para CÁ, ao lado do botão. Antes ela só aparecia no `status`, no topo do
    // painel: num formulário de onze campos, quem tocou no botão não vê o topo da tela, e a
    // recusa ficava invisível.
    setErro(await aplicarConferencia(numericos));
  };

  // O caminho feliz não pode parecer um pedido de correção: quando nada está duvidoso, o
  // formulário existe só para o usuário bater o olho e aceitar.
  const tudoConfiavel = leitura.missing_keys.length === 0 && !leitura.requires_review;

  // Um aviso cruzado acusa campos que, isolados, passaram no OCR: sem destacá-los aqui o
  // usuário leria "os valores não fecham" sem saber onde olhar.
  const camposComAviso = new Set(leitura.avisos.flatMap((aviso) => aviso.campos));

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      // Nenhuma validação nativa: ela recusa o envio sem deixar rastro visível perto do
      // botão. Quem valida é `handleSubmit`, que escreve o motivo logo acima dele.
      noValidate
      className="mt-3 border-t border-gray-200 pt-3"
    >
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
            // `text`, e não `number`: com `type="number"` o navegador RECUSA em silêncio o
            // que ele considera inválido. Uma vírgula decimal esvazia o campo sem avisar, e
            // um `required` vazio bloqueia o submit exibindo um balão preso ao input — que,
            // numa barra lateral rolada até o botão, aparece fora da tela. O resultado é um
            // botão que parece não fazer nada. A validação toda mora em `handleSubmit`.
            type="text"
            // O fluxo inteiro acontece no celular, logo após a foto: teclado numérico.
            inputMode="decimal"
            value={valores[campo.key] ?? ""}
            onChange={(event) =>
              setValores((atual) => ({ ...atual, [campo.key]: event.target.value }))
            }
            className={`w-full rounded-md border px-1.5 py-1 text-right ${
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
      {perguntandoMotivo ? (
        <div className="mt-2 rounded-md border border-slate-300 bg-slate-50 p-2">
          <p className="mb-1.5 text-[12px] text-slate-700">O que houve com esta leitura?</p>
          <div className="grid grid-cols-2 gap-1.5">
            {MOTIVOS.map(({ valor, rotulo }) => (
              <ActionButton
                key={valor}
                variante="ghost"
                className="text-[12px]"
                onClick={() => descartarLeitura(valor)}
              >
                {rotulo}
              </ActionButton>
            ))}
          </div>
          <div className="mt-1.5 flex gap-1.5">
            {/* Sair sem responder continua descartando: obrigar a escolher trocaria um
                rótulo ausente por um rótulo chutado, que é pior para o corpus. */}
            <ActionButton
              variante="ghost"
              className="flex-1 text-[12px]"
              onClick={() => descartarLeitura(null)}
            >
              Só descartar
            </ActionButton>
            <ActionButton
              variante="ghost"
              className="flex-1 text-[12px]"
              onClick={() => setPerguntandoMotivo(false)}
            >
              Voltar
            </ActionButton>
          </div>
        </div>
      ) : (
        <ActionButton
          variante="ghost"
          className="mt-2 w-full"
          onClick={() => setPerguntandoMotivo(true)}
          disabled={aplicando}
        >
          Descartar leitura
        </ActionButton>
      )}
    </form>
  );
}
