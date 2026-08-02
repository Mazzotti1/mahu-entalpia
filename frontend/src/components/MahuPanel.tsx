import { useCallback, useRef, useState, type ChangeEvent } from "react";

import { CameraModal } from "@/components/CameraModal";
import { MahuReviewForm } from "@/components/MahuReviewForm";
import { ActionButton } from "@/components/ui/ActionButton";
import { Panel } from "@/components/ui/Panel";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { travarOrientacao } from "@/lib/orientacao";
import { useMahuStore } from "@/store/useMahuStore";

export function MahuPanel() {
  const arquivoRef = useRef<HTMLInputElement>(null);
  const [cameraAberta, setCameraAberta] = useState(false);

  const status = useMahuStore((state) => state.status);
  const lendo = useMahuStore((state) => state.lendo);
  const fase = useMahuStore((state) => state.fase);
  const progressoUpload = useMahuStore((state) => state.progressoUpload);
  const segundosDecorridos = useMahuStore((state) => state.segundosDecorridos);
  const leitura = useMahuStore((state) => state.leitura);
  const leituraId = useMahuStore((state) => state.leituraId);
  const lerImagem = useMahuStore((state) => state.lerImagem);
  const setStatus = useMahuStore((state) => state.setStatus);

  const escolherArquivo = useCallback(() => arquivoRef.current?.click(), []);

  /**
   * A tela do MAHU é 2,5:1: deitado, o painel preenche o quadro e os dígitos chegam ao OCR
   * com o dobro da resolução linear. A trava é pedida antes de montar o modal para o vídeo
   * já iniciar no tamanho final — abrir e girar depois faz o `getUserMedia` negociar a
   * resolução na orientação errada.
   */
  const abrirCamera = useCallback(async () => {
    await travarOrientacao("landscape");
    setCameraAberta(true);
  }, []);

  /** Fecha o modal e prende o app em retrato: só o botão de captura volta a deitar a tela. */
  const fecharCamera = useCallback(() => {
    setCameraAberta(false);
    void travarOrientacao("portrait");
  }, []);

  const handleArquivo = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Limpa antes de processar para permitir reenviar o mesmo arquivo.
    event.target.value = "";
    if (file) {
      void lerImagem(file);
    }
  };

  const handleCaptura = (file: File) => {
    fecharCamera();
    void lerImagem(file);
  };

  // Sem getUserMedia (contexto inseguro) o fluxo cai no input com `capture`, que abre a
  // câmera nativa no celular.
  const handleIndisponivel = useCallback(
    (mensagem: string) => {
      fecharCamera();
      setStatus(mensagem);
      escolherArquivo();
    },
    [escolherArquivo, fecharCamera, setStatus],
  );

  return (
    <Panel title="Leitura MAHU">
      <ActionButton className="w-full" disabled={lendo} onClick={() => void abrirCamera()}>
        {lendo ? "Lendo..." : "Capturar monitor MAHU"}
      </ActionButton>

      <input
        ref={arquivoRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={handleArquivo}
      />

      {fase === "enviando" && (
        <ProgressBar
          // Sem nenhum evento de progresso ainda — ou porque acabou de começar, ou porque
          // o navegador não sabe o tamanho total — a barra fica indeterminada em vez de
          // travada em 0%.
          valor={progressoUpload > 0 ? progressoUpload : null}
          rotulo="Enviando a foto"
          detalhe={progressoUpload > 0 ? `${progressoUpload}%` : `${segundosDecorridos}s`}
        />
      )}
      {fase === "processando" && (
        <ProgressBar
          // O servidor lê a imagem numa chamada só e não reporta fração: o que dá para
          // mostrar de honesto é há quanto tempo está rodando.
          valor={null}
          rotulo="Lendo o painel"
          detalhe={`${segundosDecorridos}s`}
        />
      )}

      <p className="mt-2 text-xs whitespace-pre-line text-slate-600">{status}</p>

      {leitura && <MahuReviewForm key={leituraId} leitura={leitura} />}

      {cameraAberta && (
        <CameraModal
          onCapturar={handleCaptura}
          onFechar={fecharCamera}
          onIndisponivel={handleIndisponivel}
        />
      )}
    </Panel>
  );
}
