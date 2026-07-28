/** Formata com vírgula decimal, como o resto da interface em pt-BR. */
export function formatarNumero(valor: number, casas: number): string {
  if (!Number.isFinite(valor)) {
    return "—";
  }
  return valor.toFixed(casas).replace(".", ",");
}

/** Percentual de confiança do OCR (0..1 no backend) como inteiro. */
export function formatarConfianca(confianca: number | null): string {
  if (confianca == null) {
    return "—";
  }
  return `${Math.round(confianca * 100)}%`;
}
