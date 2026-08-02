import { useEffect, useState } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { useCamera } from "@/hooks/useCamera";

interface CameraModalProps {
  onCapturar: (file: File) => void;
  onFechar: () => void;
  /** Chamado quando a câmera não abre; o pai cai no seletor de arquivos. */
  onIndisponivel: (mensagem: string) => void;
}

export function CameraModal({ onCapturar, onFechar, onIndisponivel }: CameraModalProps) {
  const { videoRef, dica, indisponivel, enquadramento, capturar } = useCamera(true);
  // Pré-voo sem viagem extra: o guia já mediu um quadro há menos de dois segundos, e mandar
  // outro no disparo só adicionaria latência para reconfirmar o que já se sabe. Quando o
  // enquadramento não está pronto, o botão avisa e o segundo toque manda assim mesmo — o
  // usuário é quem está olhando o painel, e travar a captura seria pior que uma foto ruim.
  const [insistindo, setInsistindo] = useState(false);
  const bloqueado = enquadramento != null && !enquadramento.pronto && !insistindo;

  useEffect(() => {
    if (indisponivel) {
      onIndisponivel(indisponivel);
    }
  }, [indisponivel, onIndisponivel]);

  useEffect(() => {
    const aoTeclar = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onFechar();
      }
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onFechar]);

  const tirarFoto = async () => {
    if (bloqueado) {
      setInsistindo(true);
      return;
    }
    const file = await capturar();
    if (file) {
      onCapturar(file);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Capturar monitor MAHU"
      className="fixed inset-0 z-10 flex items-center justify-center bg-slate-900/70 p-4"
    >
      {/*
        Deitado o modal vira duas colunas: a dica manda segurar o celular na horizontal,
        então é nessa orientação que ele precisa caber. Empilhado, o vídeo mais o título
        mais os botões estouram os ~390px de altura de um celular na horizontal.
      */}
      <div className="flex max-h-full w-[min(720px,100%)] flex-col overflow-y-auto rounded-xl bg-white p-4 paisagem:w-full paisagem:flex-row paisagem:gap-3 paisagem:p-3">
        <h2 className="mb-3 text-lg font-semibold paisagem:hidden">Capturar monitor MAHU</h2>

        <div className="relative overflow-hidden rounded-lg bg-slate-900 paisagem:min-w-0 paisagem:flex-1">
          <video
            ref={videoRef}
            playsInline
            autoPlay
            muted
            className="block max-h-[60vh] w-full object-contain paisagem:max-h-[calc(100dvh-3rem)]"
          />
          {/*
            A moldura tem a proporção do gabarito contra o qual o backend casa a foto
            (1200x480 = 2,5:1, em `services/mahu_ocr.py`), e não a do vídeo. Acompanhando o
            vídeo ela guiava para um enquadramento que o alinhamento depois teria de
            corrigir — é exatamente onde a homografia erra.
          */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 flex items-center justify-center p-[4%]"
          >
            {/* A moldura fica verde quando o backend diz que o enquadramento serve. É o
                retorno mais rápido possível: a pessoa vê o resultado do próprio movimento
                sem precisar ler nada. */}
            <div
              className={`aspect-5/2 w-full rounded-md border-2 border-dashed transition-colors ${
                enquadramento?.pronto ? "border-emerald-400" : "border-white/75"
              }`}
            />
          </div>

          {/* Uma instrução por vez, a mais urgente. O backend já escolheu qual. */}
          {enquadramento?.instrucao && (
            <p
              role="status"
              className="pointer-events-none absolute inset-x-2 bottom-2 rounded-md bg-slate-900/80 px-2 py-1.5 text-center text-[13px] font-medium text-white"
            >
              {enquadramento.instrucao}
            </p>
          )}
        </div>

        <div className="paisagem:flex paisagem:w-44 paisagem:shrink-0 paisagem:flex-col paisagem:overflow-y-auto">
          <p className="mt-2 text-xs whitespace-pre-line text-slate-600 paisagem:mt-0">
            {indisponivel ?? dica}
          </p>

          <div className="mt-3 flex flex-wrap gap-2 paisagem:flex-col paisagem:flex-nowrap">
            <ActionButton
              className="flex-1 basis-35"
              variante={bloqueado ? "ghost" : "primary"}
              onClick={() => void tirarFoto()}
            >
              {bloqueado ? "Tirar mesmo assim" : "Tirar foto"}
            </ActionButton>
            <ActionButton variante="ghost" className="flex-1 basis-35" onClick={onFechar}>
              Cancelar
            </ActionButton>
          </div>
        </div>
      </div>
    </div>
  );
}
