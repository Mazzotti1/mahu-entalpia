Desenvolvimento de Sistemas Térmicos

**PLANEJAMENTO TÉCNICO: CARTA PSICROMÉTRICA ASHRAE**

*Desenvolvimento de interface gráfica com dados fixos e cálculos psicrométricos*

24 de julho de 2026

1\. Stack Tecnológica

Para garantir o máximo desempenho gráfico e controle sobre os elementos normativos da ASHRAE, a stack definida foca em tecnologias nativas de web:

- **Frontend:** HTML5 + Canvas API + JavaScript (ES6+)

- **Estilização:** CSS3 (Layout responsivo para o painel de dados)

- **Cálculos:** Biblioteca interna de funções termodinâmicas (sem dependências externas)

**Decisão:** O uso da **Canvas API** é mandatório para permitir a renderização precisa das curvas de saturação e linhas de entalpia, que exigem alta densidade de pontos para suavização visual.

2\. Sistema de Coordenadas da Carta

A carta psicrométrica opera em um espaço bidimensional onde as propriedades do ar são mapeadas para coordenadas cartesianas.

- **Eixo X (horizontal):** Temperatura de Bulbo Seco (TBS) em °C

- **Eixo Y (vertical):** Umidade Absoluta / Razão de Umidade (W) em g/kg de ar seco

2.1. Limites e Configuração

const chartConfig = {
margin: { top: 60, right: 80, bottom: 80, left: 100 },\<br/\>
width: 1000,\<br/\>
height: 700,\<br/\>
tbsMin: 0,\<br/\>
tbsMax: 50,\<br/\>
wMin: 0,\<br/\>
wMax: 30, // g/kg\<br/\>
atmPressure: 101325 // Pa (Nível do mar)
};
// Conversão TBS → pixel X
function tbsToX(tbs) {
const plotW = chartConfig.width - chartConfig.margin.left - chartConfig.margin.right;
return chartConfig.margin.left + ((tbs - chartConfig.tbsMin) / (chartConfig.tbsMax - chartConfig.tbsMin)) \* plotW;
}
// Conversão W → pixel Y
function wToY(w) {
const plotH = chartConfig.height - chartConfig.margin.top - chartConfig.margin.bottom;
return chartConfig.margin.top + (1 - (w - chartConfig.wMin) / (chartConfig.wMax - chartConfig.wMin)) \* plotH;
}

3\. Fórmulas Psicrométricas

O motor de cálculo deve seguir as correlações termodinâmicas padrão para ar úmido:

const P_ATM = 101325; // Pa
// 3.1 --- Pressão de saturação de vapor (Magnus/Tetens)
function pressaoSaturacao(tbs) {
return 610.78

Math.exp((17.27

tbs) / (237.3 + tbs));
}
// 3.2 --- Umidade absoluta (W) a partir de UR e TBS
function urParaW(ur, tbs) {
const pws = pressaoSaturacao(tbs);
const pw = (ur / 100) \* pws;
return 0.622 \* pw / (P_ATM - pw); // Retorna kg/kg
}
// 3.3 --- Entalpia a partir de TBS e W
function calcularEntalpia(tbs, w) {
return 1.006

tbs + w

(2501 + 1.86 \* tbs); // kJ/kg
}
// 3.4 --- W a partir de entalpia e TBS
function entalpiaParaW(h, tbs) {
return (h - 1.006

tbs) / (2501 + 1.86

tbs);
}
// 3.5 --- UR a partir de W e TBS
function wParaUr(w, tbs) {
const pws = pressaoSaturacao(tbs);
const pw = (w \* P_ATM) / (0.622 + w);
return (pw / pws) \* 100;
}
// 3.6 --- Temperatura de bulbo úmido (Iterativo)
function calcTbu(tbs, w) {
let tbu = tbs;
for (let i = 0; i \< 100; i++) {
const pwsTbu = pressaoSaturacao(tbu);
const wSat = 0.622 \* pwsTbu / (P_ATM - pwsTbu);
if (Math.abs(wSat - w) \< 0.00001) break;
if (wSat \> w) tbu -= 0.01; else tbu += 0.01;
}
return tbu;
}
// 3.7 --- Volume específico
function volumeEspecifico(tbs, w) {
return (287.05

(tbs + 273.15)

(1 + 1.6078 \* w)) / P_ATM;
}

4\. Conversão dos Pontos de Teste

|  |  |  |  |  |
|:--:|:--:|:--:|:--:|:--:|
| **Ponto** | **Entrada** | **Cálculo** | **TBS (°C)** | **W (g/kg)** |
| P1 | UR=64,09%, TBS=20,27 | urParaW(64.09, 20.27) | 20,27 | 9,50 |
| P2 | h=36,20, TBS=12,20 | entalpiaParaW(36.20, 12.20) | 12,20 | 9,48 |
| P3 | UR=100%, TBS=8,70 | urParaW(100, 8.70) | 8,70 | 6,98 |
| P4 | W=7,3, TBS=21,2 | Direto | 21,20 | 7,30 |

5\. Ordem de Renderização Gráfica

Para garantir a legibilidade, o agente deve seguir a ordem de camadas (Z-index):

1.  **Grade Base:** Eixos TBS e W com subdivisões.

2.  **Curva de Saturação:** Linha de UR=100% calculada ponto a ponto.

3.  **Isolinhas de UR:** Curvas de 10% a 90% (cor: \#D1D5DB).

4.  **Isolinhas de Entalpia:** Linhas diagonais tracejadas (cor: \#A7F3D0).

5.  **Isolinhas de Bulbo Úmido:** Linhas contínuas finas (cor: \#BAE6FD).

6.  **Vetor de Processo:** Conexão dos pontos P1→P2→P3→P4 (cor: \#2563EB).

7.  **Pontos de Dados:** Marcadores circulares com labels (cor: \#E11D48).

6\. Tabela de Propriedades Calculadas

|  |  |  |  |  |  |  |
|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Ponto** | **TBS (°C)** | **W (g/kg)** | **UR (%)** | **h (kJ/kg)** | **TBU (°C)** | **Vol. (m³/kg)** |
| P1 | 20,27 | 9,50 | **64,09** | 44,45 | 13,87 | 0,842 |
| P2 | 12,20 | 9,48 | 87,03 | **36,20** | 10,92 | 0,815 |
| P3 | 8,70 | 6,98 | **100,00** | 26,31 | 8,70 | 0,804 |
| P4 | 21,20 | **7,30** | 47,02 | 39,90 | 12,83 | 0,846 |

7\. Checklist de Validação Técnica

- **Consistência de Unidades:** Garantir que W seja convertido de kg/kg para g/kg apenas no momento da plotagem.

- **Clipping de Curvas:** As linhas de UR e Entalpia devem ser cortadas exatamente na interseção com a curva de saturação.

- **Precisão de Saturação:** O ponto P3 deve estar exatamente sobre a linha de borda da carta.

- **Legibilidade:** Labels dos pontos não devem sobrepor as linhas de grade principais.

Local e data: São Paulo, 24 de julho de 2026

*Documento elaborado em 24 de julho de 2026. As informações contidas são de responsabilidade do solicitante.*
