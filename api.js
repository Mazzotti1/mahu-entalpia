const PORTA_API = "8000";
// Portas de servidor estático separado (Live Server, python -m http.server).
const PORTAS_ESTATICAS = new Set(["3000", "5500", "8080"]);

// Descobre a API a partir de onde a própria página foi servida: com "localhost" fixo,
// abrir a página no celular apontaria a API para o próprio celular.
function resolveApiBase() {
  const explicita = new URLSearchParams(window.location.search).get("api");
  if (explicita) {
    return `${explicita.replace(/\/+$/, "")}/api`;
  }
  if (window.location.protocol === "file:") {
    return `http://localhost:${PORTA_API}/api`;
  }
  if (PORTAS_ESTATICAS.has(window.location.port)) {
    return `${window.location.protocol}//${window.location.hostname}:${PORTA_API}/api`;
  }
  // Servida pelo próprio backend (/app/): mesma origem, sem CORS.
  return `${window.location.origin}/api`;
}

const API_BASE = resolveApiBase();

async function enviarSimulacao(payload) {
  const response = await fetch(`${API_BASE}/simulacao`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return response.json();
}

async function buscarSimulacao(id) {
  const response = await fetch(`${API_BASE}/simulacao/${id}`);
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return response.json();
}

async function calcularPonto(payload) {
  const response = await fetch(`${API_BASE}/calcular`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return response.json();
}

async function lerMahuMonitor(file) {
  const body = new FormData();
  body.append("image", file);
  const response = await fetch(`${API_BASE}/mahu/ler`, {
    method: "POST",
    body
  });
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return response.json();
}

async function criarSimulacaoMahu(campos) {
  const response = await fetch(`${API_BASE}/mahu/simulacao`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(campos)
  });
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return response.json();
}

async function readApiError(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = await response.json();
    if (data && typeof data.detail === "string") {
      return data.detail;
    }
    // Erro de validação do FastAPI (422): detail é uma lista de {loc, msg}.
    if (data && Array.isArray(data.detail)) {
      return data.detail
        .map((item) => `${(item.loc || []).slice(1).join(".") || "campo"}: ${item.msg}`)
        .join("; ");
    }
  }
  return `Falha na API (${response.status})`;
}
