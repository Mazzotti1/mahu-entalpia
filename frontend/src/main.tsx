import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "@/App";
import { AuthGate } from "@/components/AuthGate";
import "@/styles/index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Elemento #root não encontrado em index.html.");
}

createRoot(container).render(
  // O portão envolve o App inteiro: sem sessão, nenhum painel chega a ser montado, e nenhum
  // deles dispara a requisição que o backend recusaria.
  <StrictMode>
    <AuthGate>
      <App />
    </AuthGate>
  </StrictMode>,
);
