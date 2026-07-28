/** Camadas que o painel lateral liga e desliga. A curva de saturação é sempre desenhada. */
export const CHART_LAYERS = [
  { key: "dryBulb", label: "Temperatura de bulbo seco" },
  { key: "humidityRatio", label: "Umidade absoluta" },
  { key: "relativeHumidity", label: "Umidade relativa" },
  { key: "wetBulb", label: "Temperatura de bulbo úmido" },
  { key: "vaporPressure", label: "Pressão de vapor" },
  { key: "specificVolume", label: "Volume específico" },
  { key: "enthalpy", label: "Entalpia" },
] as const;

export type LayerKey = (typeof CHART_LAYERS)[number]["key"];

export type LayerVisibility = Record<LayerKey, boolean>;

export const DEFAULT_LAYER_VISIBILITY: LayerVisibility = {
  dryBulb: true,
  humidityRatio: true,
  relativeHumidity: true,
  wetBulb: true,
  vaporPressure: true,
  specificVolume: true,
  enthalpy: true,
};
