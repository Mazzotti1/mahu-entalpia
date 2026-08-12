import { useEffect, useRef, useState, type PointerEvent } from "react";

import { chartConfig } from "@/chart/config";
import { renderChart } from "@/chart/draw";
import { probeFromPointer } from "@/chart/interaction";
import { useChartStore } from "@/store/useChartStore";

interface Medida {
  largura: number;
  altura: number;
  dpr: number;
}

interface PsychrometricChartProps {
  /** Qual store ler — cada carta (atual/otimizada) tem a sua, para o cursor não se misturar. */
  useStore?: typeof useChartStore;
  /** Liga o fundo colorido das 4 regiões da estratégia otimizada. */
  mostrarRegioes?: boolean;
}

export function PsychrometricChart({
  useStore = useChartStore,
  mostrarRegioes = false,
}: PsychrometricChartProps = {}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [medida, setMedida] = useState<Medida>({ largura: 0, altura: 0, dpr: 1 });

  const layers = useStore((state) => state.layers);
  const points = useStore((state) => state.points);
  const segments = useStore((state) => state.segments);
  const probe = useStore((state) => state.probe);
  const setProbe = useStore((state) => state.setProbe);
  const resetProbe = useStore((state) => state.resetProbe);

  /**
   * O tamanho de tela do canvas vem do CSS (`aspect-ratio` mais largura ou altura cheia),
   * e é medido aqui. Um ResizeObserver cobre rotação, abrir e fechar a gaveta e resize de
   * janela numa via só — `orientationchange` sozinho perderia as outras duas.
   */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    function medir() {
      const rect = canvas!.getBoundingClientRect();
      setMedida((atual) =>
        atual.largura === rect.width &&
        atual.altura === rect.height &&
        atual.dpr === window.devicePixelRatio
          ? atual
          : { largura: rect.width, altura: rect.height, dpr: window.devicePixelRatio || 1 },
      );
    }

    // devicePixelRatio muda ao arrastar a janela para uma tela de outra densidade, e isso
    // nem sempre gera resize. A media query casa a densidade ATUAL, então precisa ser
    // recriada a cada mudança para continuar valendo.
    let consulta: MediaQueryList | null = null;

    function aoMudarDensidade() {
      medir();
      observarDensidade();
    }

    function observarDensidade() {
      consulta?.removeEventListener("change", aoMudarDensidade);
      consulta = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
      consulta.addEventListener("change", aoMudarDensidade);
    }

    medir();
    observarDensidade();
    const observador = new ResizeObserver(medir);
    observador.observe(canvas);

    return () => {
      observador.disconnect();
      consulta?.removeEventListener("change", aoMudarDensidade);
    };
  }, []);

  // Um quadro inteiro é redesenhado a cada mudança de camada, pontos, cursor ou tamanho:
  // com ~1500 amostras por curva isso custa poucos milissegundos e dispensa cache.
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || medida.largura === 0 || medida.altura === 0) {
      return;
    }

    // O buffer acompanha a densidade da tela. Sem isso ele ficava fixo em 1200x760 e, num
    // celular com dpr 3, era ampliado ~2x pelo navegador — borrando exatamente o texto dos
    // eixos, no gráfico que mais depende de linha fina legível.
    const larguraBuffer = Math.round(medida.largura * medida.dpr);
    const alturaBuffer = Math.round(medida.altura * medida.dpr);
    if (canvas.width !== larguraBuffer) {
      canvas.width = larguraBuffer;
    }
    if (canvas.height !== alturaBuffer) {
      canvas.height = alturaBuffer;
    }

    // Todo o desenho fala em coordenadas de `chartConfig` (1200x760). Esta transformação
    // mapeia esse espaço no buffer real e resolve densidade e tamanho de tela de uma vez,
    // então `draw.ts` e `interaction.ts` seguem sem saber que qualquer um dos dois existe.
    // Precisa vir depois de mexer em width/height: atribuir a eles reseta o contexto.
    ctx.setTransform(
      larguraBuffer / chartConfig.width,
      0,
      0,
      alturaBuffer / chartConfig.height,
      0,
      0,
    );
    renderChart(ctx, { layers, points, segments, probe, mostrarRegioes });
  }, [layers, points, segments, probe, medida, mostrarRegioes]);

  const lerPonteiro = (event: PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const estado = probeFromPointer(canvas, event.clientX, event.clientY);
    if (estado) {
      setProbe(estado);
    }
  };

  const aoSairDoPonteiro = (event: PointerEvent<HTMLCanvasElement>) => {
    // No toque não existe "sair da área": o dedo levanta e o evento chega junto. Zerar aí
    // apagaria a leitura no exato instante em que o usuário para para olhar o valor.
    if (event.pointerType === "mouse") {
      resetProbe();
    }
  };

  return (
    <div className="min-h-0 flex-1 paisagem:flex paisagem:items-center paisagem:justify-center">
      <canvas
        ref={canvasRef}
        className="block aspect-[1200/760] w-full max-w-[1200px] touch-none border border-gray-300 bg-white paisagem:h-full paisagem:w-auto paisagem:max-w-full"
        onPointerDown={lerPonteiro}
        onPointerMove={lerPonteiro}
        onPointerLeave={aoSairDoPonteiro}
      />
    </div>
  );
}
