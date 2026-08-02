import { useCallback, useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/http";
import { avaliarEnquadramento } from "@/services/psicrometriaApi";
import type { MahuEnquadramento } from "@/types/api";

/**
 * A tela do MAHU é bem apaisada: o gabarito do backend é 1200x480, ou seja 2,5:1
 * (`services/mahu_ocr.py`). Com o celular em pé ela ocupa uma faixa fina no meio do
 * quadro e os dígitos — que já têm ~10 px no espaço canônico — chegam ao OCR com metade
 * da resolução linear. Deitar o aparelho é a alavanca mais barata de precisão que existe
 * neste fluxo, por isso é a primeira coisa que a dica diz.
 */
const DICA_PADRAO =
  "Segure o celular deitado (na horizontal): a tela do MAHU é larga, e só assim ela " +
  "preenche o quadro e os números saem grandes.\n" +
  "Encaixe a tela inteira na moldura, aproxime até preencher e evite reflexo no vidro.";

/**
 * Alguns aparelhos abrem a traseira já com zoom digital (é comum onde a câmera "principal"
 * é um recorte de um sensor maior). Zoom digital só interpola: perde detalhe justamente nos
 * dígitos, e ainda corta a tela do MAHU fora da moldura. Volta para o mínimo quando o
 * aparelho expõe a capacidade — nem todo navegador expõe, e aí não há o que fazer.
 */
function zerarZoom(track: MediaStreamTrack): void {
  // `zoom` vem da extensão de captura de imagem e não está nos tipos padrão do DOM.
  const capacidades = track.getCapabilities?.() as { zoom?: { min: number } } | undefined;
  const minimo = capacidades?.zoom?.min;
  if (minimo === undefined) {
    return;
  }
  void track
    .applyConstraints({ advanced: [{ zoom: minimo }] } as unknown as MediaTrackConstraints)
    .catch(() => {
      // Constraint recusada: fica o zoom que o aparelho escolheu.
    });
}

/**
 * Cadência do guia ao vivo. Curto o bastante para a instrução acompanhar o movimento do
 * celular, longo o bastante para o servidor não ficar casando SIFT sem parar — e para a
 * pessoa ter tempo de reagir antes da instrução mudar.
 */
const INTERVALO_GUIA_MS = 1200;

/**
 * Largura do quadro mandado ao guia. O casamento acontece a 1200 px no backend, então mais
 * que isto é desperdício de upload; menos começa a perder os keypoints do desenho do painel.
 */
const LARGURA_GUIA = 960;

export interface UseCameraResult {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  dica: string;
  /** Mensagem quando a câmera não pôde ser aberta; nesse caso resta o seletor de arquivo. */
  indisponivel: string | null;
  /** Último veredito do guia; `null` enquanto o primeiro quadro não voltou. */
  enquadramento: MahuEnquadramento | null;
  capturar: () => Promise<File | null>;
}

/**
 * Abre a câmera enquanto `ativo` for verdadeiro e devolve o quadro capturado como File.
 * A limpeza do efeito para as tracks, então fechar o modal (ou desmontar) já libera o
 * dispositivo — sem isso o LED da câmera fica aceso depois de cancelar.
 */
export function useCamera(ativo: boolean): UseCameraResult {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [dica, setDica] = useState(DICA_PADRAO);
  const [indisponivel, setIndisponivel] = useState<string | null>(null);
  const [enquadramento, setEnquadramento] = useState<MahuEnquadramento | null>(null);

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
          facingMode: { ideal: "environment" },
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
        obtido.getVideoTracks().forEach(zerarZoom);
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
  }, [ativo]);

  // Guia ao vivo: manda um quadro reduzido de tempos em tempos e mostra o que corrigir.
  // Corrigir o ângulo ANTES de disparar é a alavanca de precisão mais barata que existe
  // aqui — a foto ruim custa 5 MB de upload, ~20 s de OCR e uma conferência inteira para
  // depois virar descarte.
  useEffect(() => {
    if (!ativo) {
      setEnquadramento(null);
      return;
    }

    let cancelado = false;
    // Uma requisição por vez. Sem isso, um servidor lento acumularia quadros em voo e as
    // instruções chegariam fora de ordem, descrevendo um enquadramento que já passou.
    let emVoo = false;

    const medir = async () => {
      if (emVoo || cancelado) {
        return;
      }
      const quadro = await capturarQuadro(videoRef.current, LARGURA_GUIA, 0.6);
      if (!quadro || cancelado) {
        return;
      }
      emVoo = true;
      try {
        const veredito = await avaliarEnquadramento(quadro);
        if (!cancelado) {
          setEnquadramento(veredito);
        }
      } catch {
        // Guia é auxílio, não requisito: sem rede, a moldura e a dica de texto continuam.
      } finally {
        emVoo = false;
      }
    };

    const relogio = window.setInterval(() => void medir(), INTERVALO_GUIA_MS);
    return () => {
      cancelado = true;
      window.clearInterval(relogio);
    };
  }, [ativo]);

  const capturar = useCallback(async (): Promise<File | null> => {
    const video = videoRef.current;
    if (!video?.videoWidth || !video.videoHeight) {
      setDica("Aguarde a câmera iniciar antes de capturar.");
      return null;
    }
    const arquivo = await capturarQuadro(video, video.videoWidth, 0.92);
    if (!arquivo) {
      setDica("Falha ao capturar o quadro da câmera.");
    }
    return arquivo;
  }, []);

  return { videoRef, dica, indisponivel, enquadramento, capturar };
}

/** Quadro atual do vídeo como JPEG, redimensionado para `largura`. */
async function capturarQuadro(
  video: HTMLVideoElement | null,
  largura: number,
  qualidade: number,
): Promise<File | null> {
  if (!video?.videoWidth || !video.videoHeight) {
    return null;
  }

  const escala = Math.min(1, largura / video.videoWidth);
  const quadro = document.createElement("canvas");
  quadro.width = Math.round(video.videoWidth * escala);
  quadro.height = Math.round(video.videoHeight * escala);
  quadro.getContext("2d")?.drawImage(video, 0, 0, quadro.width, quadro.height);

  const blob = await new Promise<Blob | null>((resolve) => {
    quadro.toBlob(resolve, "image/jpeg", qualidade);
  });
  return blob ? new File([blob], "mahu.jpg", { type: "image/jpeg" }) : null;
}
