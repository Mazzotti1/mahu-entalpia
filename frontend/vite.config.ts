import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Em produção o nginx serve o build e faz proxy de /api para o backend, então o
// frontend sempre fala com a mesma origem. No dev server o proxy abaixo reproduz
// isso, o que mantém `baseURL: "/api"` válido nos dois cenários — sem CORS.
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    // host: true expõe o dev server na rede local para testar a câmera pelo celular.
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        // O OCR roda em CPU e leva ~20 s; a primeira leitura ainda baixa os modelos.
        timeout: 300_000,
        proxyTimeout: 300_000,
      },
    },
  },
});
