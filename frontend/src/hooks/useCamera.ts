import { useCallback, useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/http";

const DICA_PADRAO = "Encaixe a tela do MAHU dentro da moldura e mantenha o enquadramento estável.";

type CameraFacing = "environment" | "user";

export interface UseCameraResult {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  dica: string;
  /** Mensagem quando a câmera não pôde ser aberta; nesse caso resta o seletor de arquivo. */
  indisponivel: string | null;
  trocarCamera: () => void;
  capturar: () => Promise<File | null>;
}

/**
 * Abre a câmera enquanto `ativo` for verdadeiro e devolve o quadro capturado como File.
 * A limpeza do efeito para as tracks, então fechar o modal (ou desmontar) já libera o
 * dispositivo — sem isso o LED da câmera fica aceso depois de cancelar.
 */
export function useCamera(ativo: boolean): UseCameraResult {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [facing, setFacing] = useState<CameraFacing>("environment");
  const [dica, setDica] = useState(DICA_PADRAO);
  const [indisponivel, setIndisponivel] = useState<string | null>(null);

  useEffect(() => {
    if (!ativo) {
      return;
    }
    // getUserMedia exige contexto seguro (https ou localhost). Onde não houver, o input
    // com `capture` ainda abre a câmera nativa no celular.
    if (!navigator.mediaDevices?.getUserMedia) {
      setIndisponivel("Câmera indisponível neste contexto. Escolha uma foto do dispositivo.");
      return;
    }

    const video = videoRef.current;
    let cancelado = false;
    let stream: MediaStream | null = null;

    setIndisponivel(null);
    setDica(DICA_PADRAO);

    navigator.mediaDevices
      .getUserMedia({
        video: {
          facingMode: { ideal: facing },
          // O painel tem dígitos de poucos pixels: pede a maior resolução disponível.
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      })
      .then((obtido) => {
        stream = obtido;
        if (cancelado) {
          obtido.getTracks().forEach((track) => track.stop());
          return;
        }
        if (video) {
          video.srcObject = obtido;
        }
      })
      .catch((error: unknown) => {
        if (!cancelado) {
          setIndisponivel(`Não foi possível abrir a câmera: ${describeError(error)}`);
        }
      });

    return () => {
      cancelado = true;
      stream?.getTracks().forEach((track) => track.stop());
      if (video) {
        video.srcObject = null;
      }
    };
  }, [ativo, facing]);

  const trocarCamera = useCallback(() => {
    setFacing((atual) => (atual === "environment" ? "user" : "environment"));
  }, []);

  const capturar = useCallback(async (): Promise<File | null> => {
    const video = videoRef.current;
    if (!video?.videoWidth || !video.videoHeight) {
      setDica("Aguarde a câmera iniciar antes de capturar.");
      return null;
    }

    const quadro = document.createElement("canvas");
    quadro.width = video.videoWidth;
    quadro.height = video.videoHeight;
    quadro.getContext("2d")?.drawImage(video, 0, 0, quadro.width, quadro.height);

    const blob = await new Promise<Blob | null>((resolve) => {
      quadro.toBlob(resolve, "image/jpeg", 0.92);
    });
    if (!blob) {
      setDica("Falha ao capturar o quadro da câmera.");
      return null;
    }
    return new File([blob], "mahu.jpg", { type: "image/jpeg" });
  }, []);

  return { videoRef, dica, indisponivel, trocarCamera, capturar };
}
