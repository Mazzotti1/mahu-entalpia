import { chartConfig, getPlotBounds, tbsToX, wToY } from "@/chart/config";
import type { LayerVisibility } from "@/chart/layers";
import { desenharFundoRegioes } from "@/chart/regioes";
import {
  calcularEntalpia,
  entalpiaParaW,
  urParaW,
  wDePressaoVapor,
  wDeVolumeEspecifico,
} from "@/lib/psicrometria";
import type { ProbeState, ProcessPoint, ProcessSegment } from "@/types/chart";

/** Ordem de camadas da §5 do planejamento técnico, do fundo para a frente. */
const CORES = {
  fundo: "#ffffff",
  gradeMenor: "#f1f5f9",
  gradeMaior: "#d1d5db",
  eixo: "#374151",
  rotuloEixo: "#111827",
  rotuloTick: "#6b7280",
  saturacao: "#6b7280",
  umidadeRelativa: "#d1d5db",
  rotuloUmidadeRelativa: "#9ca3af",
  entalpia: "#a7f3d0",
  bulboUmido: "#bae6fd",
  pressaoVapor: "#e5e7eb",
  volumeEspecifico: "#c7d2fe",
  vetorProcesso: "#2563eb",
  pontoProcesso: "#e11d48",
  cursor: "#ef4444",
} as const;

/** Passo de amostragem das curvas em °C: denso o bastante para a linha sair suave. */
const PASSO_CURVA = 0.2;

interface Ponto {
  x: number;
  y: number;
}

/** `null` marca uma quebra na curva (trecho fora da carta ou acima da saturação). */
type Traco = (Ponto | null)[];

export interface ChartScene {
  layers: LayerVisibility;
  points: ProcessPoint[];
  /** Vazio quando os pontos não vieram de um processo; aí eles são ligados por reta. */
  segments: ProcessSegment[];
  probe: ProbeState | null;
  /** Liga o fundo colorido das 4 regiões da estratégia otimizada — só na carta otimizada. */
  mostrarRegioes?: boolean;
}

/** Cor por tipo de etapa: a carta passa a dizer QUAL equipamento fez cada trecho. */
const CORES_ETAPA: Record<ProcessSegment["tipo"], string> = {
  resfriamento_sensivel: "#0ea5e9",
  resfriamento_desumidificacao: "#2563eb",
  aquecimento_sensivel: "#ef4444",
  umidificacao_adiabatica: "#10b981",
  nula: "#94a3b8",
};

const ROTULOS_ETAPA: Record<ProcessSegment["tipo"], string> = {
  resfriamento_sensivel: "Resfriamento sensível",
  resfriamento_desumidificacao: "Resfriamento + desumidificação",
  aquecimento_sensivel: "Aquecimento sensível",
  umidificacao_adiabatica: "Umidificação adiabática",
  nula: "Etapa pulada",
};

/** Desenha um quadro inteiro da carta. Chamar isto substitui o conteúdo do canvas. */
export function renderChart(ctx: CanvasRenderingContext2D, scene: ChartScene): void {
  ctx.clearRect(0, 0, chartConfig.width, chartConfig.height);
  desenharFundo(ctx);
  if (scene.mostrarRegioes) {
    desenharFundoRegioes(ctx);
  }
  desenharEixosEGrade(ctx, scene.layers);
  desenharCurvaSaturacao(ctx);
  desenharIsolinhasUmidadeRelativa(ctx, scene.layers);
  desenharIsolinhasEntalpia(ctx, scene.layers);
  desenharIsolinhasBulboUmido(ctx, scene.layers);
  desenharIsolinhasPressaoVapor(ctx, scene.layers);
  desenharIsolinhasVolumeEspecifico(ctx, scene.layers);
  if (scene.segments.length > 0) {
    desenharTrajetorias(ctx, scene.segments);
    desenharLegendaEtapas(ctx, scene.segments);
  } else {
    desenharVetorProcesso(ctx, scene.points);
  }
  desenharPontosProcesso(ctx, scene.points);
  if (scene.probe) {
    desenharCursor(ctx, scene.probe);
  }
}

/**
 * Traça cada etapa pelo caminho que o ar de fato percorre, e não pela reta entre os dois
 * estados. A diferença não é enfeite: resfriar com condensação sai do ponto a W constante,
 * dobra no orvalho e desce colado na curva de saturação. A reta cortaria por dentro da
 * região supersaturada, que é ar que não existe.
 */
function desenharTrajetorias(ctx: CanvasRenderingContext2D, segments: ProcessSegment[]): void {
  ctx.save();
  ctx.lineWidth = 2.6;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  for (const segmento of segments) {
    ctx.strokeStyle = CORES_ETAPA[segmento.tipo];
    ctx.beginPath();
    ctx.moveTo(tbsToX(segmento.inicio.tbs), wToY(segmento.inicio.wGkg));

    if (segmento.tipo === "umidificacao_adiabatica") {
      // Bulbo úmido constante: a linha sobe inclinada para a esquerda até saturar. Amostrar
      // a isoentálpica aproxima bem o suficiente na escala da carta e evita inverter TBU.
      tracarPorEntalpia(ctx, segmento);
    } else if (segmento.joelho) {
      // Trecho reto a W constante até o orvalho, e daí sobre a saturação.
      ctx.lineTo(tbsToX(segmento.joelho.tbs), wToY(segmento.joelho.wGkg));
      tracarSaturacao(ctx, segmento.joelho.tbs, segmento.fim.tbs);
    } else if (saoAmbosSaturados(segmento)) {
      tracarSaturacao(ctx, segmento.inicio.tbs, segmento.fim.tbs);
    } else {
      // Sensível puro: W não muda, a linha é horizontal.
      ctx.lineTo(tbsToX(segmento.fim.tbs), wToY(segmento.fim.wGkg));
    }

    ctx.stroke();
    desenharSeta(ctx, segmento);
  }
  ctx.restore();
}

function saoAmbosSaturados(segmento: ProcessSegment): boolean {
  const folga = 0.02;
  return (
    segmento.inicio.wGkg >= urParaW(100, segmento.inicio.tbs) * 1000 - folga &&
    segmento.fim.wGkg >= urParaW(100, segmento.fim.tbs) * 1000 - folga
  );
}

/** Segue a curva de saturação entre duas temperaturas, em qualquer sentido. */
function tracarSaturacao(ctx: CanvasRenderingContext2D, de: number, para: number): void {
  const passo = de <= para ? PASSO_CURVA : -PASSO_CURVA;
  const passos = Math.max(1, Math.ceil(Math.abs(para - de) / PASSO_CURVA));
  for (let i = 1; i <= passos; i += 1) {
    const t = i === passos ? para : de + passo * i;
    ctx.lineTo(tbsToX(t), wToY(urParaW(100, t) * 1000));
  }
}

/** Segue a isoentálpica do estado inicial até a temperatura final. */
function tracarPorEntalpia(ctx: CanvasRenderingContext2D, segmento: ProcessSegment): void {
  const h = calcularEntalpia(segmento.inicio.tbs, segmento.inicio.wGkg / 1000);
  const passos = Math.max(
    1,
    Math.ceil(Math.abs(segmento.fim.tbs - segmento.inicio.tbs) / PASSO_CURVA),
  );
  for (let i = 1; i <= passos; i += 1) {
    const t =
      segmento.inicio.tbs + ((segmento.fim.tbs - segmento.inicio.tbs) * i) / passos;
    ctx.lineTo(tbsToX(t), wToY(entalpiaParaW(h, t) * 1000));
  }
}

/** Ponta de seta no fim do trecho: sem ela a carta não diz para onde o processo anda. */
function desenharSeta(ctx: CanvasRenderingContext2D, segmento: ProcessSegment): void {
  const referencia = segmento.joelho ?? segmento.inicio;
  const x = tbsToX(segmento.fim.tbs);
  const y = wToY(segmento.fim.wGkg);
  const angulo = Math.atan2(y - wToY(referencia.wGkg), x - tbsToX(referencia.tbs));
  const tamanho = 9;

  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(
    x - tamanho * Math.cos(angulo - Math.PI / 7),
    y - tamanho * Math.sin(angulo - Math.PI / 7),
  );
  ctx.lineTo(
    x - tamanho * Math.cos(angulo + Math.PI / 7),
    y - tamanho * Math.sin(angulo + Math.PI / 7),
  );
  ctx.closePath();
  ctx.fillStyle = CORES_ETAPA[segmento.tipo];
  ctx.fill();
}

function desenharLegendaEtapas(
  ctx: CanvasRenderingContext2D,
  segments: ProcessSegment[],
): void {
  const tipos = [...new Set(segments.map((s) => s.tipo))];
  const plot = getPlotBounds();
  ctx.save();
  ctx.font = "12px Segoe UI";
  ctx.textBaseline = "middle";

  let y = plot.top + 12;
  for (const tipo of tipos) {
    ctx.strokeStyle = CORES_ETAPA[tipo];
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(plot.left + 12, y);
    ctx.lineTo(plot.left + 40, y);
    ctx.stroke();

    ctx.fillStyle = CORES.rotuloEixo;
    ctx.fillText(ROTULOS_ETAPA[tipo], plot.left + 48, y);
    y += 18;
  }
  ctx.restore();
}

function desenharFundo(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = CORES.fundo;
  ctx.fillRect(0, 0, chartConfig.width, chartConfig.height);
}

function desenharEixosEGrade(ctx: CanvasRenderingContext2D, layers: LayerVisibility): void {
  const plot = getPlotBounds();
  ctx.lineWidth = 1;
  ctx.font = "12px Segoe UI";
  ctx.fillStyle = CORES.rotuloTick;

  if (layers.dryBulb) {
    for (let t = chartConfig.tbsMin; t <= chartConfig.tbsMax; t += 1) {
      const x = tbsToX(t);
      const principal = t % 5 === 0;
      ctx.beginPath();
      ctx.strokeStyle = principal ? CORES.gradeMaior : CORES.gradeMenor;
      ctx.moveTo(x, plot.top);
      ctx.lineTo(x, plot.bottom);
      ctx.stroke();
      if (principal) {
        ctx.fillText(String(t), x - 6, plot.bottom + 20);
      }
    }
  }

  if (layers.humidityRatio) {
    for (let w = chartConfig.wMin; w <= chartConfig.wMax; w += 1) {
      const y = wToY(w);
      const principal = w % 5 === 0;
      ctx.beginPath();
      ctx.strokeStyle = principal ? CORES.gradeMaior : CORES.gradeMenor;
      ctx.moveTo(plot.left, y);
      ctx.lineTo(plot.right, y);
      ctx.stroke();
      if (principal) {
        ctx.fillText(String(w), plot.right + 8, y + 4);
      }
    }
  }

  ctx.strokeStyle = CORES.eixo;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.moveTo(plot.left, plot.top);
  ctx.lineTo(plot.left, plot.bottom);
  ctx.lineTo(plot.right, plot.bottom);
  ctx.stroke();

  ctx.fillStyle = CORES.rotuloEixo;
  ctx.font = "14px Segoe UI";
  ctx.fillText("Dry Bulb Temperature (°C)", (plot.left + plot.right) / 2 - 70, plot.bottom + 45);
  ctx.save();
  ctx.translate(plot.right + 55, (plot.top + plot.bottom) / 2 + 40);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Specific Humidity (g/kg)", 0, 0);
  ctx.restore();
}

function desenharCurvaSaturacao(ctx: CanvasRenderingContext2D): void {
  const traco = construirTraco((t) => {
    const sat = urParaW(100, t) * 1000;
    return sat <= chartConfig.wMax ? sat : null;
  });
  desenharPolilinha(ctx, traco, CORES.saturacao, 2.2);
}

function desenharIsolinhasUmidadeRelativa(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.relativeHumidity) {
    return;
  }
  for (let ur = 10; ur <= 90; ur += 10) {
    const traco = construirTraco((t) => recortarNaSaturacao(urParaW(ur, t) * 1000, t));
    desenharPolilinha(ctx, traco, CORES.umidadeRelativa, 1.1);

    const rotulo = pontoEmFracao(traco, 0.92);
    if (rotulo) {
      ctx.fillStyle = CORES.rotuloUmidadeRelativa;
      ctx.font = "12px Segoe UI";
      ctx.fillText(`${ur}%`, rotulo.x - 4, rotulo.y - 4);
    }
  }
}

function desenharIsolinhasEntalpia(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.enthalpy) {
    return;
  }
  for (let h = 10; h <= 120; h += 2) {
    const traco = construirTraco((t) => recortarNaSaturacao(entalpiaParaW(h, t) * 1000, t));
    // Múltiplos de 10 ganham traço mais forte e rótulo, como referência de leitura.
    const destaque = h % 10 === 0;
    ctx.setLineDash(destaque ? [7, 4] : [3, 4]);
    desenharPolilinha(ctx, traco, CORES.entalpia, destaque ? 1.2 : 0.8);
    ctx.setLineDash([]);

    if (destaque) {
      const rotulo = primeiroPonto(traco);
      if (rotulo) {
        ctx.fillStyle = CORES.rotuloTick;
        ctx.font = "11px Segoe UI";
        ctx.fillText(String(h), rotulo.x - 16, rotulo.y + 2);
      }
    }
  }

  ctx.save();
  ctx.translate(tbsToX(19), wToY(20));
  ctx.rotate(-0.62);
  ctx.fillStyle = CORES.eixo;
  ctx.font = "15px Segoe UI";
  ctx.fillText("Enthalpy (kJ/kg)", 0, 0);
  ctx.restore();
}

function desenharIsolinhasBulboUmido(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.wetBulb) {
    return;
  }
  for (let tbu = 0; tbu <= 30; tbu += 2) {
    // A isolinha de TBU é a isentálpica que passa pelo ar saturado naquela temperatura.
    const hSaturacao = calcularEntalpia(tbu, urParaW(100, tbu));
    const traco = construirTraco((t) => {
      if (t < tbu) {
        return null;
      }
      return recortarNaSaturacao(entalpiaParaW(hSaturacao, t) * 1000, t);
    });
    desenharPolilinha(ctx, traco, CORES.bulboUmido, 0.9);
  }
}

function desenharIsolinhasPressaoVapor(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.vaporPressure) {
    return;
  }
  const plot = getPlotBounds();
  // Pressão de vapor depende só de W, então as isolinhas são horizontais.
  for (let kPa = 0.2; kPa <= 3.2; kPa += 0.2) {
    const wGkg = wDePressaoVapor(kPa * 1000) * 1000;
    if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax) {
      continue;
    }
    const y = wToY(wGkg);
    ctx.beginPath();
    ctx.strokeStyle = CORES.pressaoVapor;
    ctx.lineWidth = 0.8;
    ctx.setLineDash([2, 6]);
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function desenharIsolinhasVolumeEspecifico(
  ctx: CanvasRenderingContext2D,
  layers: LayerVisibility,
): void {
  if (!layers.specificVolume) {
    return;
  }
  for (let v = 0.78; v <= 0.98; v += 0.01) {
    const traco = construirTraco((t) => recortarNaSaturacao(wDeVolumeEspecifico(v, t) * 1000, t));
    desenharPolilinha(ctx, traco, CORES.volumeEspecifico, 0.9);
  }
}

function desenharVetorProcesso(ctx: CanvasRenderingContext2D, points: ProcessPoint[]): void {
  if (points.length < 2) {
    return;
  }
  ctx.beginPath();
  ctx.strokeStyle = CORES.vetorProcesso;
  ctx.lineWidth = 2.2;
  points.forEach((ponto, indice) => {
    const x = tbsToX(ponto.tbs);
    const y = wToY(ponto.wKgKg * 1000);
    if (indice === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
}

interface GrupoPontoProcesso {
  tbs: number;
  wKgKg: number;
  nomes: string[];
}

/**
 * Junta pontos consecutivos que caem exatamente na mesma posição — o que acontece sempre
 * que uma etapa sai `nula` (`processo.py: precisa_umidificar = false`, ou W já bate no
 * setpoint saturado): P2/P3/P4 viram o mesmo estado físico com nomes diferentes. Sem
 * agrupar, cada um desenha seu dot+rótulo em cima do anterior e o de baixo some por
 * completo — foi o que sumiu com o P2 numa entrada fria/úmida o bastante para saturar
 * sozinha na serpentina.
 */
function agruparPontosCoincidentes(points: ProcessPoint[]): GrupoPontoProcesso[] {
  const grupos: GrupoPontoProcesso[] = [];
  for (const ponto of points) {
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.tbs === ponto.tbs && ultimo.wKgKg === ponto.wKgKg) {
      ultimo.nomes.push(ponto.nome);
    } else {
      grupos.push({ tbs: ponto.tbs, wKgKg: ponto.wKgKg, nomes: [ponto.nome] });
    }
  }
  return grupos;
}

/**
 * Rótulo acima ou abaixo do ponto conforme o vizinho, em vez de deslocamento fixo por
 * nome. Com o processo, o número de pontos e a posição deles mudam com os setpoints — uma
 * tabela P1..P4 escrita à mão deixaria P5 sem regra e erraria assim que a carta mudasse.
 */
function deslocamentoDoRotulo(
  grupos: GrupoPontoProcesso[],
  indice: number,
): { dx: number; dy: number } {
  const atual = grupos[indice];
  const vizinho = grupos[indice + 1] ?? grupos[indice - 1];
  // Vizinho acima empurra o rótulo para baixo, e vice-versa.
  const acima = vizinho ? vizinho.wKgKg > atual.wKgKg : false;
  const direita = vizinho ? vizinho.tbs > atual.tbs : true;
  return { dx: direita ? -26 : 10, dy: acima ? 18 : -10 };
}

function desenharPontosProcesso(ctx: CanvasRenderingContext2D, points: ProcessPoint[]): void {
  const grupos = agruparPontosCoincidentes(points);

  grupos.forEach((grupo, indice) => {
    const x = tbsToX(grupo.tbs);
    const y = wToY(grupo.wKgKg * 1000);

    ctx.beginPath();
    ctx.fillStyle = CORES.pontoProcesso;
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();

    const rotulo = grupo.nomes.join("/");
    const deslocamento = deslocamentoDoRotulo(grupos, indice);
    ctx.font = "bold 12px Segoe UI";
    // Halo branco: os rótulos passam sobre as isolinhas e o texto sumia em cima delas.
    ctx.lineWidth = 3;
    ctx.strokeStyle = CORES.fundo;
    ctx.strokeText(rotulo, x + deslocamento.dx, y + deslocamento.dy);
    ctx.fillStyle = CORES.rotuloEixo;
    ctx.fillText(rotulo, x + deslocamento.dx, y + deslocamento.dy);
  });
}

function desenharCursor(ctx: CanvasRenderingContext2D, probe: ProbeState): void {
  const x = tbsToX(probe.tbs);
  const y = wToY(probe.wKgKg * 1000);
  const plot = getPlotBounds();

  ctx.save();
  ctx.strokeStyle = CORES.cursor;
  ctx.lineWidth = 1.2;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(x, plot.top);
  ctx.lineTo(x, plot.bottom);
  ctx.moveTo(plot.left, y);
  ctx.lineTo(plot.right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.lineWidth = 1.8;
  ctx.moveTo(x - 12, y);
  ctx.lineTo(x + 12, y);
  ctx.moveTo(x, y - 12);
  ctx.lineTo(x, y + 12);
  ctx.stroke();
  ctx.restore();
}

/**
 * Corta a curva na interseção com a curva de saturação e nos limites da carta —
 * o item de clipping do checklist da §7. Fora desses limites o traço quebra.
 */
function recortarNaSaturacao(wGkg: number, tbs: number): number | null {
  if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax) {
    return null;
  }
  return wGkg > urParaW(100, tbs) * 1000 ? null : wGkg;
}

/** Amostra uma curva W(TBS) ao longo do eixo, inserindo quebras onde ela sai da carta. */
function construirTraco(resolver: (tbs: number) => number | null): Traco {
  const traco: Traco = [];
  for (let t = chartConfig.tbsMin; t <= chartConfig.tbsMax; t += PASSO_CURVA) {
    const w = resolver(t);
    if (w == null || Number.isNaN(w)) {
      if (traco.length > 0 && traco[traco.length - 1] !== null) {
        traco.push(null);
      }
      continue;
    }
    traco.push({ x: tbsToX(t), y: wToY(w) });
  }
  return traco;
}

function desenharPolilinha(
  ctx: CanvasRenderingContext2D,
  traco: Traco,
  cor: string,
  espessura: number,
): void {
  ctx.beginPath();
  ctx.strokeStyle = cor;
  ctx.lineWidth = espessura;
  let desenhando = false;
  for (const ponto of traco) {
    if (!ponto) {
      desenhando = false;
      continue;
    }
    if (desenhando) {
      ctx.lineTo(ponto.x, ponto.y);
    } else {
      ctx.moveTo(ponto.x, ponto.y);
      desenhando = true;
    }
  }
  ctx.stroke();
}

function primeiroPonto(traco: Traco): Ponto | null {
  return traco.find((ponto): ponto is Ponto => ponto !== null) ?? null;
}

function pontoEmFracao(traco: Traco, fracao: number): Ponto | null {
  return traco[Math.floor(traco.length * fracao)] ?? null;
}
