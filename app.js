const P_ATM = 101325;

const chartConfig = {
  margin: { top: 60, right: 80, bottom: 80, left: 100 },
  width: 1200,
  height: 760,
  tbsMin: 0,
  tbsMax: 50,
  wMin: 0,
  wMax: 30
};

const layerVisibility = {
  dryBulb: true,
  humidityRatio: true,
  relativeHumidity: true,
  wetBulb: true,
  vaporPressure: true,
  specificVolume: true,
  enthalpy: true
};

// Mesmos valores do monitor em docs/foto do mahu.png, com o mesmo mapeamento que
// backend/services/mahu.py usa: assim a carta inicial e a vinda da câmera coincidem.
// P2 vem de TT_04 saturado — a entrada do doc §6 (TBS 12,20 + h 36,20) exigiria
// W = 9,48 g/kg contra W_sat = 8,85 g/kg, ou seja UR de 107%, e é rejeitada pela API.
const defaultSimulationInput = [
  { label: "P1", tbs: 20.27, ur: 63.89 },
  { label: "P2", tbs: 12.2, ur: 100.0 },
  { label: "P3", tbs: 8.7, ur: 100.0 },
  { label: "P4", tbs: 21.2, ur: 46.48 }
];

const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");
const indicatorEl = document.getElementById("indicator");
const propertiesBody = document.getElementById("properties-body");
const openCameraBtn = document.getElementById("open-camera-btn");
const mahuImageInput = document.getElementById("mahu-image-input");
const mahuStatusEl = document.getElementById("mahu-status");
const mahuReviewEl = document.getElementById("mahu-review");
const mahuFieldsEl = document.getElementById("mahu-fields");
const mahuDiscardBtn = document.getElementById("mahu-discard");
const cameraModal = document.getElementById("camera-modal");
const cameraVideo = document.getElementById("camera-video");
const cameraHintEl = document.getElementById("camera-hint");
const cameraShootBtn = document.getElementById("camera-shoot");
const cameraSwitchBtn = document.getElementById("camera-switch");
const cameraFileBtn = document.getElementById("camera-file");
const cameraCloseBtn = document.getElementById("camera-close");

let processPoints = [];
let probeState = null;
let cameraStream = null;
let cameraFacing = "environment";

setupToggles();
setupMahuCapture();
drawChart();
bootstrap().catch((error) => {
  setIndicatorError(error.message);
});

canvas.addEventListener("mousemove", (event) => {
  const point = getStateFromMouse(event);
  if (!point) {
    return;
  }
  probeState = point;
  drawChart();
  drawProbe(point.tbs, point.wKgKg);
  updateIndicator(point.tbs, point.wKgKg);
});

canvas.addEventListener("mouseleave", () => {
  if (!processPoints.length) {
    return;
  }
  probeState = { tbs: processPoints[0].tbs, wKgKg: processPoints[0].wKgKg };
  drawChart();
  updateIndicator(probeState.tbs, probeState.wKgKg);
});

async function bootstrap() {
  await loadSimulation({
    nome: "Simulação Padrão ASHRAE",
    descricao: "Pontos de processo da carta psicrométrica",
    pontos: defaultSimulationInput
  });
}

async function loadSimulation(payload) {
  const simulacao = await enviarSimulacao(payload);
  applySimulationData(simulacao);
}

function applySimulationData(simulacao) {
  processPoints = simulacao.pontos.map((point) => ({
    id: point.id,
    name: point.label,
    tbs: point.tbs,
    wKgKg: point.w / 1000,
    ur: point.ur,
    entalpia: point.entalpia,
    tbu: point.tbu,
    volume_especifico: point.volume_especifico,
    ponto_orvalho: point.ponto_orvalho,
    fonte_calculo: point.fonte_calculo
  }));
  if (!processPoints.length) {
    throw new Error("A API retornou uma simulação sem pontos.");
  }
  populatePropertiesTable();
  probeState = { tbs: processPoints[0].tbs, wKgKg: processPoints[0].wKgKg };
  drawChart();
  updateIndicator(probeState.tbs, probeState.wKgKg);
}

function setupToggles() {
  document.querySelectorAll("input[data-layer]").forEach((input) => {
    input.addEventListener("change", () => {
      layerVisibility[input.dataset.layer] = input.checked;
      drawChart();
      if (probeState) {
        drawProbe(probeState.tbs, probeState.wKgKg);
        updateIndicator(probeState.tbs, probeState.wKgKg);
      }
    });
  });
}

function setupMahuCapture() {
  if (!openCameraBtn || !mahuImageInput) {
    return;
  }

  openCameraBtn.addEventListener("click", openCamera);
  cameraShootBtn.addEventListener("click", takePhoto);
  cameraCloseBtn.addEventListener("click", closeCamera);
  cameraSwitchBtn.addEventListener("click", switchCamera);
  cameraFileBtn.addEventListener("click", () => {
    closeCamera();
    mahuImageInput.click();
  });
  mahuDiscardBtn.addEventListener("click", hideReview);
  mahuReviewEl.addEventListener("submit", applyReview);

  mahuImageInput.addEventListener("change", async () => {
    const selected = mahuImageInput.files && mahuImageInput.files[0];
    mahuImageInput.value = "";
    if (selected) {
      await readMahuImage(selected);
    }
  });
}

async function openCamera() {
  // getUserMedia exige contexto seguro (https, localhost ou file://). Onde não houver,
  // o input com capture ainda abre a câmera nativa no celular.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setMahuStatus("Câmera indisponível neste contexto. Escolha uma foto do dispositivo.");
    mahuImageInput.click();
    return;
  }

  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: cameraFacing },
        // O painel tem dígitos de poucos pixels: pede a maior resolução disponível.
        width: { ideal: 1920 },
        height: { ideal: 1080 }
      },
      audio: false
    });
  } catch (error) {
    setMahuStatus(`Não foi possível abrir a câmera: ${describeError(error)}`);
    mahuImageInput.click();
    return;
  }

  cameraVideo.srcObject = cameraStream;
  cameraModal.hidden = false;
  cameraHintEl.textContent = "Encaixe a tela do MAHU dentro da moldura e mantenha o enquadramento estável.";
}

function closeCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  cameraVideo.srcObject = null;
  cameraModal.hidden = true;
}

async function switchCamera() {
  cameraFacing = cameraFacing === "environment" ? "user" : "environment";
  closeCamera();
  await openCamera();
}

async function takePhoto() {
  if (!cameraVideo.videoWidth || !cameraVideo.videoHeight) {
    cameraHintEl.textContent = "Aguarde a câmera iniciar antes de capturar.";
    return;
  }

  const frame = document.createElement("canvas");
  frame.width = cameraVideo.videoWidth;
  frame.height = cameraVideo.videoHeight;
  frame.getContext("2d").drawImage(cameraVideo, 0, 0, frame.width, frame.height);
  const blob = await new Promise((resolve) => frame.toBlob(resolve, "image/jpeg", 0.92));

  closeCamera();
  if (!blob) {
    setMahuStatus("Falha ao capturar o quadro da câmera.");
    return;
  }
  await readMahuImage(new File([blob], "mahu.jpg", { type: "image/jpeg" }));
}

async function readMahuImage(file) {
  hideReview();
  openCameraBtn.disabled = true;
  // O OCR roda em CPU e leva ~20 s: sem esse aviso a espera parece travamento.
  setMahuStatus("Lendo a imagem do MAHU... isso leva alguns segundos.");
  try {
    const leitura = await lerMahuMonitor(file);
    if (leitura.missing_keys.length) {
      renderReview(leitura);
      const nomes = leitura.missing_keys.join(", ");
      setMahuStatus(`Leitura incompleta. Preencha à mão: ${nomes}`);
      return;
    }
    if (leitura.requires_review) {
      renderReview(leitura);
      setMahuStatus("Leitura concluída com campos duvidosos. Confira os valores e aplique.");
      return;
    }
    // Todos os campos obrigatórios saíram confiáveis: aplica direto.
    await loadSimulation(leitura.suggested_simulacao);
    setMahuStatus(`Leitura aplicada.\n${summarizeFields(leitura.campos)}`);
  } catch (error) {
    const message = describeError(error);
    setMahuStatus(`Falha na leitura MAHU: ${message}`);
    setIndicatorError(message);
  } finally {
    openCameraBtn.disabled = false;
  }
}

function renderReview(leitura) {
  mahuFieldsEl.innerHTML = "";
  leitura.campos.forEach((campo) => {
    const row = document.createElement("label");
    row.className = `review-row review-row--${campo.status}`;

    const name = document.createElement("span");
    name.className = "review-label";
    name.textContent = `${campo.label} (${campo.unidade})`;
    row.appendChild(name);

    const input = document.createElement("input");
    input.type = "number";
    input.step = "0.01";
    input.dataset.key = campo.key;
    input.value = campo.pv == null ? "" : campo.pv;
    // Os informativos não alimentam o cálculo: ficam como conferência visual.
    input.disabled = !campo.obrigatorio;
    input.required = campo.obrigatorio;
    row.appendChild(input);

    const badge = document.createElement("span");
    badge.className = "review-badge";
    badge.textContent = describeStatus(campo);
    row.appendChild(badge);

    mahuFieldsEl.appendChild(row);
  });
  mahuReviewEl.hidden = false;
}

function hideReview() {
  mahuReviewEl.hidden = true;
  mahuFieldsEl.innerHTML = "";
}

async function applyReview(event) {
  event.preventDefault();
  const campos = {};
  for (const input of mahuFieldsEl.querySelectorAll("input[data-key]")) {
    if (input.disabled) {
      continue;
    }
    const valor = Number(input.value);
    if (input.value === "" || Number.isNaN(valor)) {
      setMahuStatus(`Preencha um valor numérico para ${input.dataset.key}.`);
      input.focus();
      return;
    }
    campos[input.dataset.key] = valor;
  }

  setMahuStatus("Calculando pontos a partir dos valores conferidos...");
  try {
    applySimulationData(await criarSimulacaoMahu(campos));
    hideReview();
    setMahuStatus("Carta atualizada com a leitura conferida do MAHU.");
  } catch (error) {
    const message = describeError(error);
    setMahuStatus(`Falha ao aplicar a leitura: ${message}`);
    setIndicatorError(message);
  }
}

function describeStatus(campo) {
  if (campo.pv == null) {
    return "não lido";
  }
  if (campo.status === "ok") {
    return `ok ${Math.round(campo.confidence * 100)}%`;
  }
  return `confira ${Math.round(campo.confidence * 100)}%`;
}

function summarizeFields(campos) {
  return campos
    .filter((campo) => campo.obrigatorio && campo.pv != null)
    .map((campo) => `${campo.label}: ${campo.pv} ${campo.unidade}`)
    .join(" | ");
}

function describeError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Falha desconhecida na leitura MAHU.";
}

function drawChart() {
  ctx.clearRect(0, 0, chartConfig.width, chartConfig.height);
  drawBackground();
  drawBaseAxesAndGrid();
  drawSaturationCurve();
  drawRelativeHumidityCurves();
  drawEnthalpyLines();
  drawWetBulbLines();
  drawVaporPressureLines();
  drawSpecificVolumeLines();
  drawProcessVector();
  drawProcessPoints();
}

function drawBackground() {
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, chartConfig.width, chartConfig.height);
}

function drawBaseAxesAndGrid() {
  const plot = getPlotBounds();
  if (layerVisibility.dryBulb || layerVisibility.humidityRatio) {
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 1;
    ctx.font = "12px Segoe UI";
    ctx.fillStyle = "#6b7280";
  }

  if (layerVisibility.dryBulb) {
    for (let t = chartConfig.tbsMin; t <= chartConfig.tbsMax; t += 1) {
      const x = tbsToX(t);
      const major = t % 5 === 0;
      ctx.beginPath();
      ctx.strokeStyle = major ? "#d1d5db" : "#f1f5f9";
      ctx.moveTo(x, plot.top);
      ctx.lineTo(x, plot.bottom);
      ctx.stroke();

      if (major) {
        ctx.fillText(String(t), x - 6, plot.bottom + 20);
      }
    }
  }

  if (layerVisibility.humidityRatio) {
    for (let w = chartConfig.wMin; w <= chartConfig.wMax; w += 1) {
      const y = wToY(w);
      const major = w % 5 === 0;
      ctx.beginPath();
      ctx.strokeStyle = major ? "#d1d5db" : "#f1f5f9";
      ctx.moveTo(plot.left, y);
      ctx.lineTo(plot.right, y);
      ctx.stroke();

      if (major) {
        ctx.fillText(String(w), plot.right + 8, y + 4);
      }
    }
  }

  ctx.strokeStyle = "#374151";
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.moveTo(plot.left, plot.top);
  ctx.lineTo(plot.left, plot.bottom);
  ctx.lineTo(plot.right, plot.bottom);
  ctx.stroke();

  ctx.fillStyle = "#111827";
  ctx.font = "14px Segoe UI";
  ctx.fillText("Dry Bulb Temperature (°C)", (plot.left + plot.right) / 2 - 70, plot.bottom + 45);
  ctx.save();
  ctx.translate(plot.right + 55, (plot.top + plot.bottom) / 2 + 40);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Specific Humidity (g/kg)", 0, 0);
  ctx.restore();
}

function drawSaturationCurve() {
  const points = buildCurvePoints((t) => {
    const sat = urParaW(100, t) * 1000;
    return sat <= chartConfig.wMax ? sat : null;
  });
  drawPolyline(points, "#6b7280", 2.2);
}

function drawRelativeHumidityCurves() {
  if (!layerVisibility.relativeHumidity) {
    return;
  }
  for (let rh = 10; rh <= 90; rh += 10) {
    const points = buildCurvePoints((t) => {
      const wGkg = urParaW(rh, t) * 1000;
      const sat = urParaW(100, t) * 1000;
      if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax || wGkg > sat) {
        return null;
      }
      return wGkg;
    });
    drawPolyline(points, "#d1d5db", 1.1);

    const labelPoint = points[Math.floor(points.length * 0.92)];
    if (labelPoint) {
      ctx.fillStyle = "#9ca3af";
      ctx.font = "12px Segoe UI";
      ctx.fillText(`${rh}%`, labelPoint.x - 4, labelPoint.y - 4);
    }
  }
}

function drawEnthalpyLines() {
  if (!layerVisibility.enthalpy) {
    return;
  }
  for (let h = 10; h <= 120; h += 2) {
    const points = buildCurvePoints((t) => {
      const wGkg = entalpiaParaW(h, t) * 1000;
      const sat = urParaW(100, t) * 1000;
      if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax || wGkg > sat) {
        return null;
      }
      return wGkg;
    });
    const strong = h % 10 === 0;
    ctx.setLineDash(strong ? [7, 4] : [3, 4]);
    drawPolyline(points, "#a7f3d0", strong ? 1.2 : 0.8);
    ctx.setLineDash([]);
    if (strong && points.length > 0) {
      const p = points[0];
      ctx.fillStyle = "#6b7280";
      ctx.font = "11px Segoe UI";
      ctx.fillText(String(h), p.x - 16, p.y + 2);
    }
  }

  ctx.save();
  ctx.translate(tbsToX(19), wToY(20));
  ctx.rotate(-0.62);
  ctx.fillStyle = "#374151";
  ctx.font = "15px Segoe UI";
  ctx.fillText("Enthalpy (kJ/kg)", 0, 0);
  ctx.restore();
}

function drawWetBulbLines() {
  if (!layerVisibility.wetBulb) {
    return;
  }

  for (let twb = 0; twb <= 30; twb += 2) {
    const hAtSaturation = calcularEntalpia(twb, urParaW(100, twb));
    const points = buildCurvePoints((t) => {
      if (t < twb) {
        return null;
      }
      const wGkg = entalpiaParaW(hAtSaturation, t) * 1000;
      const sat = urParaW(100, t) * 1000;
      if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax || wGkg > sat) {
        return null;
      }
      return wGkg;
    });
    drawPolyline(points, "#bae6fd", 0.9);
  }
}

function drawVaporPressureLines() {
  if (!layerVisibility.vaporPressure) {
    return;
  }
  for (let kPa = 0.2; kPa <= 3.2; kPa += 0.2) {
    const wGkg = (0.622 * (kPa * 1000) / (P_ATM - kPa * 1000)) * 1000;
    if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax) {
      continue;
    }
    const y = wToY(wGkg);
    const plot = getPlotBounds();
    ctx.beginPath();
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 0.8;
    ctx.setLineDash([2, 6]);
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function drawSpecificVolumeLines() {
  if (!layerVisibility.specificVolume) {
    return;
  }
  for (let v = 0.78; v <= 0.98; v += 0.01) {
    const points = buildCurvePoints((t) => {
      const w = ((v * P_ATM) / (287.05 * (t + 273.15)) - 1) / 1.6078;
      const wGkg = w * 1000;
      const sat = urParaW(100, t) * 1000;
      if (wGkg < chartConfig.wMin || wGkg > chartConfig.wMax || wGkg > sat) {
        return null;
      }
      return wGkg;
    });
    drawPolyline(points, "#c7d2fe", 0.9);
  }
}

function drawProcessVector() {
  if (!processPoints.length) {
    return;
  }
  const vectorPoints = processPoints.map((p) => ({
    x: tbsToX(p.tbs),
    y: wToY(p.wKgKg * 1000)
  }));
  ctx.beginPath();
  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2.2;
  vectorPoints.forEach((p, i) => {
    if (i === 0) {
      ctx.moveTo(p.x, p.y);
    } else {
      ctx.lineTo(p.x, p.y);
    }
  });
  ctx.stroke();
}

function drawProcessPoints() {
  if (!processPoints.length) {
    return;
  }
  const labels = {
    P1: { dx: 10, dy: -12 },
    P2: { dx: -22, dy: -8 },
    P3: { dx: -10, dy: -14 },
    P4: { dx: 10, dy: -8 }
  };

  for (const p of processPoints) {
    const x = tbsToX(p.tbs);
    const y = wToY(p.wKgKg * 1000);

    ctx.beginPath();
    ctx.fillStyle = "#e11d48";
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();

    const offset = labels[p.name] || { dx: 8, dy: -8 };
    ctx.fillStyle = "#111827";
    ctx.font = "bold 12px Segoe UI";
    ctx.fillText(p.name, x + offset.dx, y + offset.dy);
  }
}

function drawProbe(tbs, wKgKg) {
  const x = tbsToX(tbs);
  const y = wToY(wKgKg * 1000);
  const plot = getPlotBounds();

  ctx.save();
  ctx.strokeStyle = "#ef4444";
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
  ctx.strokeStyle = "#ef4444";
  ctx.lineWidth = 1.8;
  ctx.moveTo(x - 12, y);
  ctx.lineTo(x + 12, y);
  ctx.moveTo(x, y - 12);
  ctx.lineTo(x, y + 12);
  ctx.stroke();
  ctx.restore();
}

function populatePropertiesTable() {
  propertiesBody.innerHTML = "";
  processPoints.forEach((point) => {
    const tr = document.createElement("tr");
    const values = [
      point.name,
      formatNum(point.tbs, 2),
      formatNum(point.wKgKg * 1000, 2),
      formatNum(point.ur, 2),
      formatNum(point.entalpia, 2),
      formatNum(point.tbu, 2),
      formatNum(point.volume_especifico, 3)
    ];

    values.forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    propertiesBody.appendChild(tr);
  });
}

function updateIndicator(tbs, wKgKg) {
  const rh = wParaUr(wKgKg, tbs);
  const h = calcularEntalpia(tbs, wKgKg);
  const tbu = calcTbu(tbs, wKgKg);
  const vol = volumeEspecifico(tbs, wKgKg);
  const pw = vaporPressureFromW(wKgKg);
  const dew = dewPointFromVaporPressure(pw);

  indicatorEl.textContent = [
    `Dry Bulb: ${formatNum(tbs, 2)} °C`,
    `Rel Humidity: ${formatNum(rh, 2)} %`,
    `Abs Humidity: ${formatNum(wKgKg * 1000, 4)} g/kg`,
    `Vap Pressure: ${formatNum(pw / 1000, 4)} kPa`,
    `Air Volume: ${formatNum(vol, 4)} m³/kg`,
    `Enthalpy: ${formatNum(h, 4)} kJ/kg`,
    `Dew Point: ${formatNum(dew, 2)} °C`,
    `Wet Bulb: ${formatNum(tbu, 2)} °C`
  ].join("\n");
}

function setIndicatorError(message) {
  indicatorEl.textContent = `Erro de integração com backend:\n${message}`;
}

function setMahuStatus(message) {
  if (!mahuStatusEl) {
    return;
  }
  mahuStatusEl.textContent = message;
}

function pressaoSaturacao(tbs) {
  return 610.78 * Math.exp((17.27 * tbs) / (237.3 + tbs));
}

function urParaW(ur, tbs) {
  const pws = pressaoSaturacao(tbs);
  const pw = (ur / 100) * pws;
  return 0.622 * pw / (P_ATM - pw);
}

function calcularEntalpia(tbs, w) {
  return 1.006 * tbs + w * (2501 + 1.86 * tbs);
}

function entalpiaParaW(h, tbs) {
  return (h - 1.006 * tbs) / (2501 + 1.86 * tbs);
}

function wParaUr(w, tbs) {
  const pws = pressaoSaturacao(tbs);
  const pw = (w * P_ATM) / (0.622 + w);
  return (pw / pws) * 100;
}

function calcTbu(tbs, w) {
  const hTarget = calcularEntalpia(tbs, w);
  let low = -20;
  let high = tbs;
  for (let i = 0; i < 60; i++) {
    const mid = (low + high) / 2;
    const wSat = urParaW(100, mid);
    const hMid = calcularEntalpia(mid, wSat);
    if (hMid > hTarget) {
      high = mid;
    } else {
      low = mid;
    }
  }
  return (low + high) / 2;
}

function volumeEspecifico(tbs, w) {
  return (287.05 * (tbs + 273.15) * (1 + 1.6078 * w)) / P_ATM;
}

function vaporPressureFromW(w) {
  return (w * P_ATM) / (0.622 + w);
}

function dewPointFromVaporPressure(pw) {
  const lnTerm = Math.log(pw / 610.78);
  return (237.3 * lnTerm) / (17.27 - lnTerm);
}

function tbsToX(tbs) {
  const plotW = chartConfig.width - chartConfig.margin.left - chartConfig.margin.right;
  return chartConfig.margin.left + ((tbs - chartConfig.tbsMin) / (chartConfig.tbsMax - chartConfig.tbsMin)) * plotW;
}

function wToY(wGkg) {
  const plotH = chartConfig.height - chartConfig.margin.top - chartConfig.margin.bottom;
  return chartConfig.margin.top + (1 - (wGkg - chartConfig.wMin) / (chartConfig.wMax - chartConfig.wMin)) * plotH;
}

function yToW(y) {
  const plotH = chartConfig.height - chartConfig.margin.top - chartConfig.margin.bottom;
  const scaled = 1 - (y - chartConfig.margin.top) / plotH;
  return chartConfig.wMin + scaled * (chartConfig.wMax - chartConfig.wMin);
}

function xToTbs(x) {
  const plotW = chartConfig.width - chartConfig.margin.left - chartConfig.margin.right;
  const scaled = (x - chartConfig.margin.left) / plotW;
  return chartConfig.tbsMin + scaled * (chartConfig.tbsMax - chartConfig.tbsMin);
}

function getPlotBounds() {
  return {
    left: chartConfig.margin.left,
    top: chartConfig.margin.top,
    right: chartConfig.width - chartConfig.margin.right,
    bottom: chartConfig.height - chartConfig.margin.bottom
  };
}

function buildCurvePoints(valueResolver) {
  const points = [];
  for (let t = chartConfig.tbsMin; t <= chartConfig.tbsMax; t += 0.2) {
    const w = valueResolver(t);
    if (w == null || Number.isNaN(w)) {
      if (points.length > 0 && points[points.length - 1] !== null) {
        points.push(null);
      }
      continue;
    }
    points.push({ x: tbsToX(t), y: wToY(w) });
  }
  return points;
}

function drawPolyline(points, strokeStyle, lineWidth) {
  ctx.beginPath();
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = lineWidth;
  let drawing = false;
  for (const p of points) {
    if (!p) {
      drawing = false;
      continue;
    }
    if (!drawing) {
      ctx.moveTo(p.x, p.y);
      drawing = true;
    } else {
      ctx.lineTo(p.x, p.y);
    }
  }
  ctx.stroke();
}

function formatNum(value, digits) {
  return Number(value).toFixed(digits).replace(".", ",");
}

function getStateFromMouse(event) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = chartConfig.width / rect.width;
  const scaleY = chartConfig.height / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;

  const bounds = getPlotBounds();
  if (x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) {
    return null;
  }

  const tbs = xToTbs(x);
  const wGkg = yToW(y);
  const sat = urParaW(100, tbs) * 1000;
  if (wGkg > sat || wGkg < 0) {
    return null;
  }

  return { tbs, wKgKg: wGkg / 1000 };
}
