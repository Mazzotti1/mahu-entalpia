import { useEffect } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { useCamera } from "@/hooks/useCamera";

interface CameraModalProps {
  onCapturar: (file: File) => void;
  onFechar: () => void;
  onEscolherArquivo: () => void;
  /** Chamado quando a câmera não abre; o pai cai no seletor de arquivos. */
  onIndisponivel: (mensagem: string) => void;
}

export function CameraModal({
  onCapturar,
  onFechar,
  onEscolherArquivo,
  onIndisponivel,
}: CameraModalProps) {
  const { videoRef, dica, indisponivel, trocarCamera, capturar } = useCamera(true);

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
      <div className="max-h-full w-[min(720px,100%)] overflow-y-auto rounded-xl bg-white p-4">
        <h2 className="mb-3 text-lg font-semibold">Capturar monitor MAHU</h2>

        <div className="relative overflow-hidden rounded-lg bg-slate-900">
          <video
            ref={videoRef}
            playsInline
            autoPlay
            muted
            className="block max-h-[60vh] w-full object-contain"
          />
          {/* A leitura assume que a tela do MAHU preenche o quadro: a moldura mostra onde encaixá-la. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-[8%] inset-x-[5%] rounded-md border-2 border-dashed border-white/75"
          />
        </div>

        <p className="mt-2 text-xs whitespace-pre-line text-slate-600">{indisponivel ?? dica}</p>

        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton className="flex-1 basis-35" onClick={() => void tirarFoto()}>
            Tirar foto
          </ActionButton>
          <ActionButton variante="ghost" className="flex-1 basis-35" onClick={trocarCamera}>
            Trocar câmera
          </ActionButton>
          <ActionButton variante="ghost" className="flex-1 basis-35" onClick={onEscolherArquivo}>
            Escolher arquivo
          </ActionButton>
          <ActionButton variante="ghost" className="flex-1 basis-35" onClick={onFechar}>
            Cancelar
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
