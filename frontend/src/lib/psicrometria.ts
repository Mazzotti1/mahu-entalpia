/**
 * Correlações psicrométricas usadas apenas para desenhar a carta e alimentar o indicador
 * sob o cursor — as duas coisas precisam de milhares de avaliações por quadro e não
 * podem ir à rede. As propriedades dos pontos do processo continuam vindo do backend,
 * que usa psychrolib (ASHRAE).
 */

/** Pressão atmosférica ao nível do mar (Pa). */
export const P_ATM = 101325;

/** Pressão de saturação de vapor pela correlação de Magnus/Tetens (Pa). */
export function pressaoSaturacao(tbs: number): number {
  return 610.78 * Math.exp((17.27 * tbs) / (237.3 + tbs));
}

/** Umidade absoluta (kg/kg) a partir de umidade relativa (%) e TBS (°C). */
export function urParaW(ur: number, tbs: number): number {
  const pws = pressaoSaturacao(tbs);
  const pw = (ur / 100) * pws;
  return (0.622 * pw) / (P_ATM - pw);
}

/** Entalpia (kJ/kg) a partir de TBS (°C) e umidade absoluta (kg/kg). */
export function calcularEntalpia(tbs: number, w: number): number {
  return 1.006 * tbs + w * (2501 + 1.86 * tbs);
}

/** Umidade absoluta (kg/kg) a partir de entalpia (kJ/kg) e TBS (°C). */
export function entalpiaParaW(h: number, tbs: number): number {
  return (h - 1.006 * tbs) / (2501 + 1.86 * tbs);
}

/** Umidade relativa (%) a partir de umidade absoluta (kg/kg) e TBS (°C). */
export function wParaUr(w: number, tbs: number): number {
  const pws = pressaoSaturacao(tbs);
  const pw = (w * P_ATM) / (0.622 + w);
  return (pw / pws) * 100;
}

/**
 * Temperatura de bulbo úmido (°C) por bisseção sobre a curva de saturação: TBU é a
 * temperatura em que o ar saturado tem a mesma entalpia do estado dado.
 */
export function calcTbu(tbs: number, w: number): number {
  const hAlvo = calcularEntalpia(tbs, w);
  let low = -20;
  let high = tbs;
  for (let i = 0; i < 60; i += 1) {
    const mid = (low + high) / 2;
    const hMid = calcularEntalpia(mid, urParaW(100, mid));
    if (hMid > hAlvo) {
      high = mid;
    } else {
      low = mid;
    }
  }
  return (low + high) / 2;
}

/** Volume específico (m³/kg) a partir de TBS (°C) e umidade absoluta (kg/kg). */
export function volumeEspecifico(tbs: number, w: number): number {
  return (287.05 * (tbs + 273.15) * (1 + 1.6078 * w)) / P_ATM;
}

/** Pressão parcial de vapor (Pa) a partir da umidade absoluta (kg/kg). */
export function pressaoVaporDeW(w: number): number {
  return (w * P_ATM) / (0.622 + w);
}

/** Umidade absoluta (kg/kg) a partir da pressão parcial de vapor (Pa). */
export function wDePressaoVapor(pw: number): number {
  return (0.622 * pw) / (P_ATM - pw);
}

/** Temperatura de ponto de orvalho (°C), invertendo Magnus/Tetens. */
export function pontoOrvalhoDePressaoVapor(pw: number): number {
  const lnTermo = Math.log(pw / 610.78);
  return (237.3 * lnTermo) / (17.27 - lnTermo);
}

/** Umidade absoluta (kg/kg) sobre a isolinha de volume específico `v` na temperatura `tbs`. */
export function wDeVolumeEspecifico(v: number, tbs: number): number {
  return ((v * P_ATM) / (287.05 * (tbs + 273.15)) - 1) / 1.6078;
}
